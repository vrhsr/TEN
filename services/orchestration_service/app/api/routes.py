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

def _resolve_case_id_from_task(task_id: int) -> tuple[int, dict]:
    """
    Returns (case_id, task_dict).
    Strategy 1 → API  (get_task_and_case)
    Strategy 2 → DB   (get_task_from_db)
    Raises HTTPException(404) if neither works.
    """
    task: dict = {}

    # ── Strategy 1: API ───────────────────────────────────────────────
    try:
        data = _engine.tools.get_task_and_case(task_id)   # returns flat dict

        log.info(
            "advance_task.api_lookup_ok",
            task_id  = task_id,
            keys     = list(data.keys()) if data else [],
        )

        # get_task_and_case returns {"task": {...}, "case": {...}}
        # OR a flat dict — handle both shapes defensively
        if "task" in data and "case" in data:
            task_obj = data.get("task") or {}
            case_obj = data.get("case") or {}
            case_id  = (
                case_obj.get("RCM_CASE_ID")
                or case_obj.get("case_id")
                or task_obj.get("RCM_CASE_ID")
                or task_obj.get("rcm_case_id")
            )
            task = {
                # normalise to snake_case
                "task_id"      : task_obj.get("RCM_TASK_ID") or task_obj.get("task_id"),
                "rcm_task_id"  : task_obj.get("RCM_TASK_ID") or task_obj.get("task_id"),
                "rcm_case_id"  : case_id,
                "case_id"      : case_id,
                "clinic_id"    : task_obj.get("CLINIC_ID")    or task_obj.get("clinic_id"),
                "task_type"    : task_obj.get("TASK_TYPE")    or task_obj.get("task_type"),
                "state_code"   : task_obj.get("STATE_CODE")   or task_obj.get("state_code"),
                "handler_key"  : task_obj.get("HANDLER_KEY")  or task_obj.get("handler_key"),
            }
        else:
            # flat dict shape (ToolsClient already normalised it)
            case_id = (
                data.get("RCM_CASE_ID")
                or data.get("rcm_case_id")
                or data.get("case_id")
            )
            task = data

        if case_id:
            log.info("advance_task.case_id_resolved_via_api", case_id=case_id)
            return int(case_id), task

    except Exception as exc:
        log.warning(
            "advance_task.api_lookup_failed",
            task_id = task_id,
            error   = str(exc),
        )

    # ── Strategy 2: Direct DB ─────────────────────────────────────────
    log.info("advance_task.trying_db_fallback", task_id=task_id)

    try:
        task = _engine.tools.get_task_from_db(task_id)
    except Exception as exc:
        log.error("advance_task.db_lookup_error", task_id=task_id, error=str(exc))
        raise HTTPException(
            status_code=503,
            detail=f"DB lookup failed for task {task_id}: {exc}",
        )

    if not task:
        log.warning("advance_task.not_found", task_id=task_id)
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found in API or DB",
        )

    case_id = task.get("rcm_case_id") or task.get("case_id")

    if not case_id:
        log.error("advance_task.no_case_id", task_id=task_id, task=task)
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} exists but has no associated case_id",
        )

    log.info("advance_task.case_id_resolved_via_db", case_id=case_id)
    return int(case_id), task


# ══════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════

# app/api/routes.py — add this temporary route

@router.get("/debug/db-ping")
def debug_db_ping():
    """Verify DB credentials are loading from .env correctly."""
    import pymysql
    from shared.config import get_settings

    s = get_settings()

    config = {
        "host"    : s.rcm_db_host,
        "port"    : s.rcm_db_port,
        "user"    : s.rcm_db_user,
        "password": "SET ✅" if s.rcm_db_password else "EMPTY ❌",
        "database": s.rcm_db_database,
    }

    try:
        conn = pymysql.connect(
            host            = s.rcm_db_host,
            port            = s.rcm_db_port,
            user            = s.rcm_db_user,
            password        = s.rcm_db_password,
            database        = s.rcm_db_database,
            connect_timeout = 5,
            cursorclass     = pymysql.cursors.DictCursor,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM RCM_TASK")
            row = cur.fetchone()
        conn.close()

        return {
            "status"    : "connected ✅",
            "config"    : config,
            "task_count": row["cnt"],
        }

    except Exception as exc:
        return {
            "status": "failed ❌",
            "config": config,
            "error" : str(exc),
        }

        
@router.post("/tasks/advance", response_model=AdvanceCaseOutput)
def advance_by_task(
    payload      : AdvanceByTaskInput,
    x_api_secret : str | None = Header(default=None),
):
    _verify_internal(x_api_secret)
    log.info("advance_task.start", task_id=payload.task_id)

    # ── Resolve case_id (API → DB fallback) ──────────────────────────
    case_id, task = _resolve_case_id_from_task(payload.task_id)

    log.info(
        "advance_task.dispatching",
        task_id = payload.task_id,
        case_id = case_id,
    )

    # ── Run the engine ────────────────────────────────────────────────
    try:
        result = _engine.advance_case(
            case_id        = case_id,
            correlation_id = str(uuid.uuid4()),
            task_id        = payload.task_id,
        )
    except Exception as exc:
        log.error(
            "advance_task.engine_error",
            task_id = payload.task_id,
            case_id = case_id,
            error   = str(exc),
            exc_info= True,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    log.info(
        "advance_task.done",
        task_id     = payload.task_id,
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
    payload      : AdvanceByCaseInput,
    x_api_secret : str | None = Header(default=None),
):
    """Dev / test: drive a case directly by case_id."""
    _verify_internal(x_api_secret)
    log.info("advance_case.start", case_id=payload.case_id)

    try:
        result = _engine.advance_case(
            case_id        = payload.case_id,
            correlation_id = str(uuid.uuid4()),
            task_id        = None,
        )
    except Exception as exc:
        log.error(
            "advance_case.engine_error",
            case_id  = payload.case_id,
            error    = str(exc),
            exc_info = True,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    if result.get("error") and not result.get("next_wake_at"):
        raise HTTPException(status_code=500, detail=result["error"])

    log.info(
        "advance_case.done",
        case_id     = payload.case_id,
        outcome     = result.get("outcome_code"),
        handler_key = result.get("handler_key"),
    )

    return AdvanceCaseOutput(
        case_id          = payload.case_id,
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