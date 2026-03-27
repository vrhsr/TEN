"""
WorkflowRepository — all reads and writes to the rcm_workflow database.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models.workflow import (
    RcmCase,
    RcmDocument,
    RcmEligibilityResult,
    RcmFact,
    RcmStepHistory,
    RcmTask,
)
from ..schemas.case import CaseCreate, CaseUpdate
from ..schemas.document import DocumentCreate
from ..schemas.eligibility import EligibilityResultCreate
from ..schemas.fact import FactCreate
from ..schemas.step_history import StepHistoryCreate
from ..schemas.task import TaskCreate, TaskUpdate


class WorkflowRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── RcmCase ───────────────────────────────────────────────────────────────

    def create_case(self, payload: CaseCreate) -> RcmCase:
        """Idempotent: returns the existing case when charge_id + case_type match."""
        if payload.charge_id is not None:
            existing = self.db.scalar(
                select(RcmCase).where(
                    RcmCase.case_type == payload.case_type,
                    RcmCase.charge_id == payload.charge_id,
                )
            )
            if existing:
                return existing
        row = RcmCase(**payload.model_dump())
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_case(self, case_id: int) -> RcmCase | None:
        return self.db.get(RcmCase, case_id)

    def get_case_full(self, case_id: int) -> dict[str, Any] | None:
        """Returns case + open tasks + current facts as a single dict for the orchestration layer."""
        case = self.get_case(case_id)
        if not case:
            return None
        tasks = self.list_open_tasks(case_id)
        facts = self.list_facts(case_id)
        return {
            "case_id": case.case_id,
            "case_type": case.case_type,
            "workflow_name": case.workflow_name,
            "workflow_version": case.workflow_version,
            "claim_id": case.claim_id,
            "clinic_id": case.clinic_id,
            "facility_id": case.facility_id,
            "provider_id": case.provider_id,
            "patient_id": case.patient_id,
            "payer_id": case.payer_id,
            "visit_id": case.visit_id,
            "charge_id": case.charge_id,
            "state_code": case.state_code,
            "substate_code": case.substate_code,
            "step_code": case.step_code,
            "queue_id": case.queue_id,
            "next_action_at": case.next_action_at.isoformat() if case.next_action_at else None,
            "due_at": case.due_at.isoformat() if case.due_at else None,
            "context_json": case.context_json or {},
            "terminal_outcome_code": case.terminal_outcome_code,
            "closed_at": case.closed_at.isoformat() if case.closed_at else None,
            "created_at": case.created_at.isoformat() if case.created_at else None,
            "updated_at": case.updated_at.isoformat() if case.updated_at else None,
            "open_tasks": [self._task_dict(t) for t in tasks],
            "facts": {f.fact_key: f.fact_value_str for f in facts},
        }

    def update_case(self, case_id: int, payload: CaseUpdate) -> RcmCase:
        row = self.get_case(case_id)
        if not row:
            raise ValueError(f"Case {case_id} not found")
        for k, v in payload.model_dump(exclude_none=True).items():
            setattr(row, k, v)
        self.db.commit()
        self.db.refresh(row)
        return row

    def close_case(
        self,
        case_id: int,
        terminal_outcome_code: str,
        state_code: str,
    ) -> RcmCase:
        row = self.get_case(case_id)
        if not row:
            raise ValueError(f"Case {case_id} not found")
        row.state_code = state_code
        row.terminal_outcome_code = terminal_outcome_code
        row.closed_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_cases_due(self, limit: int = 200) -> list[RcmCase]:
        """Used by the scheduler to find cases whose next_action_at has passed."""
        now = datetime.utcnow()
        return list(
            self.db.scalars(
                select(RcmCase)
                .where(
                    RcmCase.next_action_at <= now,
                    RcmCase.terminal_outcome_code.is_(None),
                )
                .order_by(RcmCase.next_action_at.asc())
                .limit(limit)
            )
        )

    # ── RcmTask ───────────────────────────────────────────────────────────────

    def get_task(self, task_id: int) -> RcmTask | None:
        return self.db.get(RcmTask, task_id)

    def upsert_task(self, payload: TaskCreate) -> RcmTask:
        task = self.db.scalar(
            select(RcmTask).where(
                RcmTask.case_id == payload.case_id,
                RcmTask.intent_key == payload.intent_key,
            )
        )
        if task:
            for k, v in payload.model_dump(exclude_none=True).items():
                setattr(task, k, v)
        else:
            task = RcmTask(**payload.model_dump())
            self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def update_task(self, task_id: int, payload: TaskUpdate) -> RcmTask:
        task = self.db.get(RcmTask, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        for k, v in payload.model_dump(exclude_none=True).items():
            setattr(task, k, v)
        self.db.commit()
        self.db.refresh(task)
        return task

    def cancel_open_tasks_for_case(
        self, case_id: int, reason: str = "SUPERSEDED"
    ) -> int:
        """Cancel all non-terminal tasks for a case. Returns count closed."""
        tasks = self.list_open_tasks(case_id)
        for t in tasks:
            t.state_code = "CANCELED"
            # close_reason_code missing in stage DB
        self.db.commit()
        return len(tasks)

    def list_open_tasks(self, case_id: int) -> list[RcmTask]:
        return list(
            self.db.scalars(
                select(RcmTask).where(
                    RcmTask.case_id == case_id,
                    RcmTask.state_code.in_(["OPEN", "IN_PROGRESS", "WAITING"]),
                )
            )
        )

    def list_tasks_by_queue(
        self, queue_id: str, state_code: str = "OPEN"
    ) -> list[RcmTask]:
        return list(
            self.db.scalars(
                select(RcmTask)
                .where(
                    RcmTask.queue_id == queue_id,
                    RcmTask.state_code == state_code,
                )
                .order_by(RcmTask.due_at.asc())
            )
        )

    def increment_task_attempts(self, task_id: int) -> RcmTask:
        task = self.db.get(RcmTask, task_id)
        if task:
            task.attempt_count = (task.attempt_count or 0) + 1
            self.db.commit()
            self.db.refresh(task)
        return task

    @staticmethod
    def _task_dict(t: RcmTask) -> dict:
        return {
            "task_id": t.task_id,
            "task_type": t.task_type,
            "intent_key": t.intent_key,
            "state_code": t.state_code,
            "queue_id": t.queue_id,
            "handler_key": t.handler_key,
            "attempt_count": t.attempt_count,
            "next_action_at": t.next_action_at.isoformat() if t.next_action_at else None,
            "payload_json": t.payload_json or {},
        }

    # ── RcmFact ───────────────────────────────────────────────────────────────

    def create_fact(self, payload: FactCreate) -> RcmFact:
        # Note: is_current and fact_scope missing in stage DB
        row = RcmFact(**payload.model_dump(exclude={"fact_scope"}))
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def bulk_create_facts(self, facts: list[FactCreate]) -> list[RcmFact]:
        return [self.create_fact(f) for f in facts]

    def list_facts(self, case_id: int) -> list[RcmFact]:
        return list(
            self.db.scalars(
                select(RcmFact).where(
                    RcmFact.case_id == case_id,
                )
            )
        )

    def get_fact(
        self, case_id: int, fact_scope: str, fact_key: str
    ) -> RcmFact | None:
        return self.db.scalar(
            select(RcmFact).where(
                RcmFact.case_id == case_id,
                RcmFact.fact_key == fact_key,
            )
        )

    # ── RcmDocument ───────────────────────────────────────────────────────────

    def create_document(self, payload: DocumentCreate) -> RcmDocument:
        row = RcmDocument(**payload.model_dump())
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_document(self, document_id: int) -> RcmDocument | None:
        return self.db.get(RcmDocument, document_id)

    def list_documents_for_case(self, case_id: int) -> list[RcmDocument]:
        return list(
            self.db.scalars(
                select(RcmDocument).where(RcmDocument.case_id == case_id)
            )
        )

    def update_document_ocr(
        self, document_id: int, ocr_text: str, status_code: str = "OCR_COMPLETE"
    ) -> None:
        doc = self.db.get(RcmDocument, document_id)
        if doc:
            doc.ocr_text = ocr_text
            doc.status_code = status_code
            self.db.commit()

    def update_document_status(self, document_id: int, status_code: str) -> None:
        doc = self.db.get(RcmDocument, document_id)
        if doc:
            doc.status_code = status_code
            self.db.commit()

    # ── RcmEligibilityResult ──────────────────────────────────────────────────

    def create_eligibility_result(
        self, payload: EligibilityResultCreate
    ) -> RcmEligibilityResult:
        row = RcmEligibilityResult(**payload.model_dump())
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_latest_eligibility_result(
        self, case_id: int, insurance_id: int | None = None
    ) -> RcmEligibilityResult | None:
        stmt = select(RcmEligibilityResult).where(
            RcmEligibilityResult.case_id == case_id
        )
        if insurance_id is not None:
            stmt = stmt.where(RcmEligibilityResult.insurance_id == insurance_id)
        stmt = stmt.order_by(RcmEligibilityResult.created_at.desc()).limit(1)
        return self.db.scalar(stmt)

    # ── RcmStepHistory ────────────────────────────────────────────────────────

    def create_step_history(self, payload: StepHistoryCreate) -> RcmStepHistory:
        row = RcmStepHistory(**payload.model_dump())
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_step_history(self, case_id: int) -> list[RcmStepHistory]:
        return list(
            self.db.scalars(
                select(RcmStepHistory)
                .where(RcmStepHistory.case_id == case_id)
                .order_by(RcmStepHistory.started_at.asc())
            )
        )
