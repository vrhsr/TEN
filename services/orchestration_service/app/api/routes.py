"""
Orchestration Service API

The single advance endpoint is the only entry point for Temporal activities
and the scheduler.  All other endpoints are diagnostic / operational.
"""
from __future__ import annotations

import uuid
from fastapi import APIRouter, HTTPException, Header

from shared.config import get_settings
from shared.logging import get_logger
from ..schemas.advance import AdvanceCaseInput, AdvanceCaseOutput, AdvanceTaskInput
from ..graph.engine import OrchestrationEngine

router = APIRouter()
log = get_logger(__name__)
settings = get_settings()

_engine = OrchestrationEngine()


def _verify_internal(x_api_secret: str | None = Header(default=None)) -> None:
    if settings.app_env != "local" and x_api_secret != settings.internal_api_secret:
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/cases/advance", response_model=AdvanceCaseOutput)
def advance_case(
    payload: AdvanceCaseInput,
    x_api_secret: str | None = Header(default=None),
):
    _verify_internal(x_api_secret)
    result = _engine.advance_case(
        case_id=payload.case_id,
        correlation_id=payload.trigger.correlation_id,
        task_id=payload.trigger.task_id,
    )
    if result.get("error") and not result.get("next_wake_at"):
        raise HTTPException(status_code=500, detail=result["error"])

    return AdvanceCaseOutput(
        case_id=payload.case_id,
        handler_key=result.get("handler_key", "UNKNOWN"),
        state_before=result.get("state_before"),
        state_after=result.get("state_after"),
        outcome_code=result.get("outcome_code"),
        note=result.get("note"),
        next_wake_at=result.get("next_wake_at"),
        confidence_score=result.get("confidence_score"),
        tools_invoked=result.get("tools_invoked", []),
        emit_events=[],
    )


@router.post("/tasks/advance", response_model=AdvanceCaseOutput)
def advance_task(
    payload: AdvanceTaskInput,
    x_api_secret: str | None = Header(default=None),
):
    log.info("advance_task.start", task_id=payload.task_id)
    _verify_internal(x_api_secret)
    task = _engine.tools.get_task(payload.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    case_id = task.get("rcm_case_id") or task.get("case_id")
    if not case_id:
        raise HTTPException(status_code=400, detail="Task does not have an associated case_id")

    # Advance the case supplying correlation_id & the known task_id
    result = _engine.advance_case(
        case_id=case_id,
        correlation_id=str(uuid.uuid4()),
        task_id=payload.task_id,
    )
    if result.get("error") and not result.get("next_wake_at"):
        raise HTTPException(status_code=500, detail=result["error"])

    return AdvanceCaseOutput(
        case_id=case_id,
        handler_key=result.get("handler_key", "UNKNOWN"),
        state_before=result.get("state_before"),
        state_after=result.get("state_after"),
        outcome_code=result.get("outcome_code"),
        note=result.get("note"),
        next_wake_at=result.get("next_wake_at"),
        confidence_score=result.get("confidence_score"),
        tools_invoked=result.get("tools_invoked", []),
        emit_events=[],
    )


@router.get("/handlers")
def list_handlers():
    """Return the registered handler keys and the states they serve."""
    from ..graph.registry import STATE_TO_HANDLER
    return {
        "handlers": list(set(STATE_TO_HANDLER.values())),
        "state_to_handler": STATE_TO_HANDLER,
    }


@router.post("/cases/{case_id}/advance-sync")
def advance_case_sync(
    case_id: int,
    x_api_secret: str | None = Header(default=None),
):
    """Convenience endpoint: advance without a full AdvanceCaseInput body."""
    _verify_internal(x_api_secret)
    result = _engine.advance_case(
        case_id=case_id,
        correlation_id=str(uuid.uuid4()),
    )
    return result
