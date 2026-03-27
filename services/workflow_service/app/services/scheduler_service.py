"""
SchedulerService

Two jobs run on the APScheduler:

  1. charge_intake_job  — polls allofactorv3 for new CLAIM rows,
     creates an RCM_CASE for each one, then immediately calls advance_case
     so the first LangGraph handler runs synchronously in the same cycle.

  2. timer_wakeup_job   — polls RCM_CASE for rows whose next_action_at
     has passed and calls advance_case for each, acting as the Temporal
     timer substitute until a real Temporal cluster is wired in.
"""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from shared.config import get_settings
from shared.constants import (
    CASE_TYPE_DEMOGRAPHICS,
    STATE_CLAIM_INITIALIZE,
    WORKFLOW_NAME_DEMOGRAPHICS,
    WORKFLOW_VERSION_V1,
)
from shared.logging import get_logger
from ..core.clients import OrchestrationClient, ToolsClient

log = get_logger(__name__)


class SchedulerService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.tools = ToolsClient()
        self.orchestration = OrchestrationClient()

    # ── Job 1: Charge intake ──────────────────────────────────────────────────

    def charge_intake_job(self) -> list[dict]:
        """
        Poll for new charges, create RCM_CASE rows (idempotent),
        and trigger the first advance_case call for each new case.
        """
        log.info("scheduler.charge_intake.start")
        try:
            charges = self.tools.get_new_charges(self.settings.scheduler_batch_size)
        except Exception as exc:
            log.error("scheduler.charge_intake.fetch_failed", error=str(exc))
            return []

        if not charges:
            log.info("scheduler.charge_intake.no_new_charges")
            return []

        log.info("scheduler.charge_intake.charges_found", count=len(charges))
        results: list[dict] = []

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(self._intake_one_charge, charge): charge
                for charge in charges
            }
            for future in as_completed(futures):
                charge = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as exc:
                    log.error(
                        "scheduler.charge_intake.charge_failed",
                        charge_id=charge.get("charge_id"),
                        error=str(exc),
                    )

        log.info(
            "scheduler.charge_intake.done",
            processed=len(results),
            total=len(charges),
        )
        return results

    def _intake_one_charge(self, charge: dict) -> dict:
        correlation_id = str(uuid.uuid4())
        case = self.tools.create_case({
            "case_type": CASE_TYPE_DEMOGRAPHICS,
            "workflow_name": WORKFLOW_NAME_DEMOGRAPHICS,
            "workflow_version": WORKFLOW_VERSION_V1,
            "claim_id": charge.get("claim_id"),
            "clinic_id": charge.get("clinic_id"),
            "facility_id": charge.get("facility_id"),
            "provider_id": charge.get("provider_id"),
            "patient_id": charge.get("patient_id"),
            "visit_id": charge.get("visit_id"),
            "charge_id": charge.get("charge_id"),
            "state_code": STATE_CLAIM_INITIALIZE,
            "context_json": {
                "source": "scheduler",
                "correlation_id": correlation_id,
                "intake_charge": charge,
            },
        })

        case_id = case["case_id"]
        is_new = case.get("state_code") == STATE_CLAIM_INITIALIZE

        log.info(
            "scheduler.case_created",
            case_id=case_id,
            charge_id=charge.get("charge_id"),
            is_new=is_new,
        )

        # Advance immediately for new cases; existing cases are picked up by timer_wakeup_job
        advance: dict[str, Any] = {}
        if is_new:
            try:
                advance = self.orchestration.advance_case(
                    case_id=case_id,
                    correlation_id=correlation_id,
                )
            except Exception as exc:
                log.error(
                    "scheduler.advance_failed",
                    case_id=case_id,
                    error=str(exc),
                )

        return {"case": case, "advance": advance, "charge_id": charge.get("charge_id")}

    # ── Job 2: Timer wakeup ───────────────────────────────────────────────────

    def timer_wakeup_job(self) -> list[dict]:
        """
        Find cases whose next_action_at has passed and advance each one.
        This replaces Temporal timer callbacks until a real Temporal worker is running.
        """
        log.info("scheduler.timer_wakeup.start")
        try:
            due_cases = self.tools.list_cases_due(limit=200)
        except Exception as exc:
            log.error("scheduler.timer_wakeup.fetch_failed", error=str(exc))
            return []

        if not due_cases:
            return []

        log.info("scheduler.timer_wakeup.cases_due", count=len(due_cases))
        results: list[dict] = []

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(self._wake_one_case, c["case_id"]): c
                for c in due_cases
            }
            for future in as_completed(futures):
                case_stub = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as exc:
                    log.error(
                        "scheduler.timer_wakeup.case_failed",
                        case_id=case_stub.get("case_id"),
                        error=str(exc),
                    )

        log.info("scheduler.timer_wakeup.done", advanced=len(results))
        return results

    def _wake_one_case(self, case_id: int) -> dict:
        correlation_id = str(uuid.uuid4())
        advance = self.orchestration.advance_case(
            case_id=case_id,
            correlation_id=correlation_id,
        )
        log.info(
            "scheduler.case_advanced",
            case_id=case_id,
            outcome_code=advance.get("outcome_code"),
            next_wake_at=advance.get("next_wake_at"),
        )
        return {"case_id": case_id, "advance": advance}
