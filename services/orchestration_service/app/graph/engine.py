"""
OrchestrationEngine — the single entry point called by Temporal activities
and the scheduler.

For each advance_case call:
  1. Load case + open tasks + facts from Tools API (single call)
  2. Resolve handler from state_code
  3. Run the appropriate LangGraph node
  4. Write step history (audit trail)
  5. Update RCM_CASE with next_state and next_wake_at
  6. Return the result dict to the caller

Errors in individual nodes are caught, logged, and stored in step_history
so the case is never silently lost.
"""
from __future__ import annotations

import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone

from shared.constants import (
    TERMINAL_STATES,
    STATE_CASE_CLOSED_DUPLICATE,
    HANDLER_INITIALIZE,
    HANDLER_GATHER_REGISTRATION,
    HANDLER_VERIFY_REGISTRATION,
    HANDLER_VERIFY_ELIGIBILITY,
    HANDLER_SELF_REGISTRATION,
    HANDLER_HOSPITAL_FACESHEET_REQUEST,
    HANDLER_NORMALIZE_CASE,
    HANDLER_CLOSE_OUT,
)
from shared.logging import get_logger
from .registry import resolve_handler
from ..clients.tools_client import ToolsClient
from ..clients.profile_engine_client import ProfileEngineClient
from ..nodes.initialize import run_initialize
from ..nodes.gather_registration import run_gather_registration
from ..nodes.verify_registration import run_verify_registration
from ..nodes.verify_eligibility import run_verify_eligibility
from ..nodes.self_registration import run_self_registration
from ..nodes.hospital_facesheet_request import run_hospital_facesheet_request
from ..nodes.normalize_case import run_normalize_case
from ..nodes.close_out import run_close_out

log = get_logger(__name__)

# Terminal states that still need a handler to run (e.g. Close Out cleanup)
_DISPATCH_TERMINAL = frozenset({STATE_CASE_CLOSED_DUPLICATE})


class OrchestrationEngine:
    def __init__(self) -> None:
        self.tools = ToolsClient()
        self.profile = ProfileEngineClient()

    def advance_case(
        self,
        case_id: int,
        correlation_id: str | None = None,
        task_id: int | None = None,
    ) -> dict:
        correlation_id = correlation_id or str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)

        log.info(
            "engine.advance_case.start",
            case_id=case_id,
            correlation_id=correlation_id,
            task_id=task_id,
        )

        # ── 1. Load full case context ─────────────────────────────────────
        case = self.tools.get_case(case_id)
        if not case:
            log.error("engine.case_not_found", case_id=case_id)
            return {
                "case_id": case_id,
                "handler_key": "UNKNOWN",
                "outcome_code": "CASE_NOT_FOUND",
                "next_state": None,
                "next_wake_at": None,
                "error": f"Case {case_id} not found",
            }

        state_code = case["state_code"]
        state_before = state_code

        # ── 2. Short-circuit terminal states ──────────────────────────────
        # CASE_CLOSED_DUPLICATE is terminal but still needs Close Out Node
        # to update task payload and signal Temporal — let it through.
        if state_code in TERMINAL_STATES and state_code not in _DISPATCH_TERMINAL:
            log.info(
                "engine.terminal_state",
                case_id=case_id,
                state_code=state_code,
                correlation_id=correlation_id,
                task_id=task_id,
            )
            return {
                "case_id": case_id,
                "handler_key": "TERMINAL",
                "outcome_code": "TERMINAL_NO_OP",
                "next_state": state_code,
                "next_wake_at": None,
            }

        # ── 3. Resolve handler ────────────────────────────────────────────
        handler_key = resolve_handler(state_code)

        log.info(
            "engine.handler_selected",
            case_id=case_id,
            handler_key=handler_key,
        )

        # ── 4. Build LangGraph state and dispatch ─────────────────────────
        graph_state = {
            "case": case,
            "task_id": task_id,
        }
        result: dict = {}
        error_detail: str | None = None
        start_time_sec = time.time()

        log.info(
            "graph.start",
            case_id=case_id,
            correlation_id=correlation_id,
            task_id=task_id,
            state_before=state_before,
            handler_key=handler_key,
        )

        try:
            result = self._dispatch(handler_key, graph_state)
        except Exception as exc:
            error_detail = traceback.format_exc()
            error_ms = round((time.time() - start_time_sec) * 1000)
            log.error(
                "graph.error",
                case_id=case_id,
                correlation_id=correlation_id,
                handler_key=handler_key,
                error_type=type(exc).__name__,
                error=str(exc),
                total_duration_ms=error_ms,
            )
            result = {
                "handler_key": handler_key,
                "next_state": state_code,
                "next_wake_at": _offset_iso(minutes=15),
                "outcome_code": "HANDLER_ERROR",
                "note": f"Handler raised exception: {exc}",
                "error": str(exc),
                "confidence_score": 0.0,
                "facts_considered": {},
                "tools_invoked": [],
            }

        # ── 5. Write step history ─────────────────────────────────────────
        ended_at = datetime.now(timezone.utc)
        try:
            self.tools.create_step_history({
                "case_id": case_id,
                "correlation_id": correlation_id,
                "trigger_type": "ADVANCE",
                "handler_key": handler_key,
                "handler_version": "v1",
                "state_before": state_before,
                "state_after": result.get("next_state", state_before),
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "outcome_code": result.get("outcome_code", "UNKNOWN"),
                "facts_considered_json": result.get("facts_considered"),
                "tools_invoked_json": {
                    "tools": result.get("tools_invoked", []),
                },
                "confidence_score": result.get("confidence_score"),
                "output_summary_json": {
                    "next_state": result.get("next_state"),
                    "note": result.get("note"),
                    "next_wake_at": result.get("next_wake_at"),
                },
                "error_detail": error_detail,
            })
        except Exception as exc:
            log.warning(
                "engine.step_history_write_failed",
                case_id=case_id,
                error=str(exc),
            )

        # ── 6. Update RCM_CASE ────────────────────────────────────────────
        next_state = result.get("next_state", state_code)
        next_wake_at = result.get("next_wake_at")
        terminal = next_state in TERMINAL_STATES

        update_payload: dict = {
            "state_code": next_state,
            "next_action_at": next_wake_at,
        }
        if terminal:
            update_payload["terminal_outcome_code"] = next_state
            update_payload["closed_at"] = ended_at.isoformat()

        # Preserve existing context_json and merge result summary
        existing_ctx = case.get("context_json") or {}
        update_payload["context_json"] = {
            **existing_ctx,
            "last_handler": handler_key,
            "last_outcome": result.get("outcome_code"),
            "last_note": result.get("note"),
            "last_advanced_at": ended_at.isoformat(),
        }

        try:
            self.tools.update_case(case_id, update_payload)
        except Exception as exc:
            log.error(
                "engine.case_update_failed",
                case_id=case_id,
                error=str(exc),
            )

        # ── 7. Log graph completion ───────────────────────────────────────
        if not error_detail:
            total_ms = round((time.time() - start_time_sec) * 1000)
            log.info(
                "graph.complete",
                case_id=case_id,
                correlation_id=correlation_id,
                handler_key=handler_key,
                state_before=state_before,
                state_after=next_state,
                outcome_code=result.get("outcome_code"),
                terminal=terminal,
                tools_invoked=result.get("tools_invoked", []),
                confidence_score=result.get("confidence_score"),
                total_duration_ms=total_ms,
            )

        return {
            "case_id": case_id,
            "handler_key": handler_key,
            "state_before": state_before,
            "state_after": next_state,
            "outcome_code": result.get("outcome_code"),
            "note": result.get("note"),
            "next_wake_at": next_wake_at,
            "confidence_score": result.get("confidence_score"),
            "tools_invoked": result.get("tools_invoked", []),
        }

    # ── Dispatch table ────────────────────────────────────────────────────

    def _dispatch(self, handler_key: str, state: dict) -> dict:
        dispatch = {
            HANDLER_INITIALIZE: lambda s: run_initialize(s, self.tools),
            HANDLER_GATHER_REGISTRATION: lambda s: run_gather_registration(
                s, self.tools, self.profile
            ),
            HANDLER_VERIFY_REGISTRATION: lambda s: run_verify_registration(
                s, self.tools
            ),
            HANDLER_VERIFY_ELIGIBILITY: lambda s: run_verify_eligibility(
                s, self.tools
            ),
            HANDLER_SELF_REGISTRATION: lambda s: run_self_registration(
                s, self.tools
            ),
            HANDLER_HOSPITAL_FACESHEET_REQUEST: lambda s: run_hospital_facesheet_request(
                s, self.tools
            ),
            HANDLER_NORMALIZE_CASE: lambda s: run_normalize_case(
                s, self.tools
            ),
            HANDLER_CLOSE_OUT: lambda s: run_close_out(s, self.tools),
        }

        fn = dispatch.get(handler_key)
        if fn is None:
            log.error(
                "engine.unknown_handler",
                case_id=state.get("case", {}).get("case_id"),
                handler_key=handler_key,
            )
            raise ValueError(
                f"No handler registered for key: {handler_key}"
            )
        return fn(state)


def _offset_iso(minutes: int = 0, hours: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(
        minutes=minutes, hours=hours
    )
    return dt.isoformat()