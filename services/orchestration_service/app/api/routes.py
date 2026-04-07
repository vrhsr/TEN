# app/api/routes.py
from __future__ import annotations

import uuid
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from shared.config import get_settings
from shared.logging import get_logger
from ..schemas.advance import AdvanceCaseOutput
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

@router.post("/tasks/advance", response_model=AdvanceCaseOutput)
def advance_by_task(
    task_id      : int,
    case_id      : int,
    x_api_secret : str | None = Header(default=None),
):
    _verify_internal(x_api_secret)
    log.info("advance_task.start", task_id=task_id, case_id=case_id)

    log.info(
        "advance_task.dispatching",
        task_id = task_id,
        case_id = case_id,
    )

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

    return AdvanceCaseOutput(
        case_id          = case_id,
        handler_key      = result.get("handler_key", "UNKNOWN"),
        state_before     = result.get("state_before"),
        state_after      = result.get("state_after"),
        outcome_code     = result.get("outcome_code"),
        note             = result.get("note"),
        next_wake_at     = result.get("next_wake_at"),
        confidence_score = result.get("confidence_score", 0.0),
        tools_invoked    = result.get("tools_invoked", []),
        emit_events      = [],
    )


@router.post("/cases/advance", response_model=AdvanceCaseOutput)
def advance_by_case(
    case_id      : int,
    x_api_secret : str | None = Header(default=None),
):
    """Dev / test: drive a case directly by case_id."""
    _verify_internal(x_api_secret)
    log.info("advance_case.start", case_id=case_id)

    try:
        result = _engine.advance_case(
            case_id        = case_id,
            correlation_id = str(uuid.uuid4()),
            task_id        = None,
        )
    except Exception as exc:
        log.error(
            "advance_case.engine_error",
            case_id  = case_id,
            error    = str(exc),
            exc_info = True,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    if result.get("error") and not result.get("next_wake_at"):
        raise HTTPException(status_code=500, detail=result["error"])

    log.info(
        "advance_case.done",
        case_id     = case_id,
        outcome     = result.get("outcome_code"),
        handler_key = result.get("handler_key"),
    )

    return AdvanceCaseOutput(
        case_id          = case_id,
        handler_key      = result.get("handler_key", "UNKNOWN"),
        state_before     = result.get("state_before"),
        state_after      = result.get("state_after"),
        outcome_code     = result.get("outcome_code"),
        note             = result.get("note"),
        next_wake_at     = result.get("next_wake_at"),
        confidence_score = result.get("confidence_score", 0.0),
        tools_invoked    = result.get("tools_invoked", []),
        emit_events      = [],
    )


@router.get("/handlers")
def list_handlers():
    """Show all registered state → handler mappings."""
    from ..graph.registry import STATE_TO_HANDLER

    return {
        "handlers"        : sorted(set(STATE_TO_HANDLER.values())),
        "state_to_handler": STATE_TO_HANDLER,
    }