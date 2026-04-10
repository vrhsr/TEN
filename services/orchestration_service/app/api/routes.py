# app/api/routes.py
from __future__ import annotations

import uuid
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from shared.config import get_settings
from shared.logging import get_logger
from ..schemas.advance import AdvanceCaseResponse, AdvanceData, AdvancePayload, AdvanceOutcome
from ..graph.engine import OrchestrationEngine

router   = APIRouter()
log      = get_logger(__name__)
settings = get_settings()
_engine  = OrchestrationEngine()


def _verify_internal(x_api_secret: str | None = None) -> None:
    if settings.app_env != "local" and x_api_secret != settings.internal_api_secret:
        raise HTTPException(status_code=401, detail="Unauthorized")


class AdvanceByTaskInput(BaseModel):
    task_id: int


class AdvanceByCaseInput(BaseModel):
    case_id: int


# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════

def _resolve_case_id_from_task(task_id: int) -> int:
    try:
        data = _engine.tools.get_task_and_case(task_id)
        if "task" in data and "case" in data:
            case_obj = data.get("case") or {}
            task_obj = data.get("task") or {}
            case_id = (
                case_obj.get("RCM_CASE_ID")
                or case_obj.get("case_id")
                or task_obj.get("RCM_CASE_ID")
                or task_obj.get("rcm_case_id")
            )
        else:
            case_id = (
                data.get("RCM_CASE_ID")
                or data.get("rcm_case_id")
                or data.get("case_id")
            )
        
        if case_id:
            return int(case_id)
            
    except Exception as exc:
        log.warning("advance_task.api_lookup_failed", task_id=task_id, error=str(exc))
        
    raise HTTPException(
        status_code=404,
        detail=f"Task {task_id} not found or no case_id resolved via API.",
    )

@router.post("/tasks/advance", response_model=AdvanceCaseResponse)
def advance_by_task(task_id: int):

    # ── Step 1: Context Initialization ───────────────────────────────
    case_id = _resolve_case_id_from_task(task_id)

    # ── Run the engine ────────────────────────────────────────────────
    try:
        result = _engine.advance_case(
            case_id        = case_id,
            correlation_id = str(uuid.uuid4()),
            task_id        = task_id,
        )
    except Exception as exc:
        log.error(
            "advance_task.engine_error",
            task_id = task_id,
            case_id = case_id,
            error   = str(exc),
            exc_info= True,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    log.info(
        "advance_task.done",
        task_id     = task_id,
        case_id     = case_id,
        outcome     = result.get("outcome_code"),
        handler_key = result.get("handler_key"),
    )

    return AdvanceCaseResponse(
        success=True,
        code=200,
        data=AdvanceData(
            payload=AdvancePayload(
                case_id=case_id,
                task_id=task_id,
                outcome=AdvanceOutcome(
                    outcome_code=result.get("outcome_code"),
                    note=result.get("note"),
                ),
                existing_facts=result.get("facts_considered", {}).get("existing", {}),
                payload_updated=True,
                extracted_entities=None,
                confidence_score=result.get("confidence_score")
            )
        )
    )





@router.get("/handlers")
def list_handlers():
    """Show all registered state → handler mappings."""
    from ..graph.registry import STATE_TO_HANDLER

    return {
        "handlers"        : sorted(set(STATE_TO_HANDLER.values())),
        "state_to_handler": STATE_TO_HANDLER,
    }