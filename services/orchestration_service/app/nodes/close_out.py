"""
Node: Close Out Case
Handler: DEMO_CLOSE_OUT

Node 4 in the Initialize Demographics Flow.

Called when the orchestration engine reaches CASE_CLOSED_DUPLICATE (or any
terminal close-out state that routes here).

Responsibilities:
  1. Update the RCM_TASK payload_json with the final outcome from upstream nodes.
  2. Set the RCM_TASK state_code to "OPEN" so Temporal picks it up.
  3. Signal Temporal with the final case state.
  4. If any errors were recorded in the state, write them to RCM_ERROR table.
"""
from __future__ import annotations

import traceback

from shared.constants import (
    HANDLER_CLOSE_OUT,
    TASK_OPEN,
)
from shared.logging import get_logger
from .common import build_result

log = get_logger(__name__)

# Signal type sent to Temporal when a case is closed out
SIGNAL_CLOSE_OUT = "CASE_CLOSED_OUT"


def run_close_out(state: dict, tools_client) -> dict:
    """
    Entry-point for the CASE_CLOSED_DUPLICATE state (and any future close-out states).

    Actions:
      1. Collect the outcome payload written by the upstream node.
      2. PATCH RCM_TASK: update payload_json + set state_code = OPEN.
      3. Signal Temporal with the close-out state.
      4. If errors present in state, write to RCM_ERROR table.
    """
    case = state["case"]
    case_id = case["case_id"]
    task_id: int | None = state.get("task_id")
    node_start = time.time()
    current_state = case.get("state_code", "UNKNOWN")
    tools_invoked: list[str] = []
    error_detail: str | None = None

    # ── Collect outcome payload from case context ──────────────────────────────
    context_json: dict = case.get("context_json") or {}
    outcome_payload = {
        "outcome": context_json.get("last_outcome", "UNKNOWN"),
        "note": context_json.get("last_note"),
        "state": current_state,
        "case_id": case_id,
        "task_id": task_id,
        "last_handler": context_json.get("last_handler"),
    }

    log.info(
        "close_out.start",
        case_id=case_id,
        task_id=task_id,
        current_state=current_state,
        outcome=outcome_payload["outcome"],
    )

    # ── 1. Update RCM_TASK: set payload + state = OPEN ────────────────────────
    if task_id:
        try:
            tools_client.update_task(task_id, {
                "state_code": TASK_OPEN,
                "result_json": outcome_payload,
            })
            tools_invoked.append("update_task:OPEN")
            log.info("close_out.task_updated", case_id=case_id, task_id=task_id)
        except Exception as exc:
            error_detail = traceback.format_exc()
            log.error(
                "node4.close_out.failed",
                case_id=case_id,
                task_id=task_id,
                error=str(exc),
                node="close_out_case",
            )
        
        node_ms = round((time.time() - node_start) * 1000)
        log.info(
            "node4.close_out.FINAL",
            case_id=case_id,
            task_id=task_id,
            next_state=STATE_CASE_CLOSED_DUPLICATE if "DUPLICATE" in state.get("outcome_code", "") else state.get("next_state"),
            outcome_code=state.get("outcome_code"),
            tools_invoked=tools_invoked,
            duration_ms=node_ms,
            node="close_out_case",
        )
    else:
        log.warning("node4.close_out.no_task_id", case_id=case_id, node="close_out_case")

    # ── 2. Signal Temporal ────────────────────────────────────────────────────
    try:
        tools_client.signal_temporal(
            case_id=case_id,
            signal_type=SIGNAL_CLOSE_OUT,
            state={
                "state_code": current_state,
                "outcome": outcome_payload["outcome"],
                "task_id": task_id,
            },
        )
        tools_invoked.append("signal_temporal:CASE_CLOSED_OUT")
        log.info("close_out.temporal_signalled", case_id=case_id, signal=SIGNAL_CLOSE_OUT)
    except Exception as exc:
        error_detail = error_detail or traceback.format_exc()
        log.error("close_out.signal_temporal_failed", case_id=case_id, error=str(exc))

    # ── 3. Log errors to RCM_ERROR table (only if something failed above) ─────
    if error_detail:
        try:
            tools_client.log_error(
                case_id=case_id,
                task_id=task_id,
                error_detail=error_detail,
                node_name="DEMO_CLOSE_OUT",
            )
            tools_invoked.append("log_error")
        except Exception as exc:
            # Best-effort — do not re-raise; case is already in terminal state
            log.error("close_out.log_error_failed", case_id=case_id, error=str(exc))

    return build_result(
        state,
        HANDLER_CLOSE_OUT,
        next_state=current_state,          # stay in terminal state, no further advance
        outcome_code="CLOSE_OUT_COMPLETE",
        note=f"Case closed out with outcome: {outcome_payload['outcome']}",
        facts_considered=outcome_payload,
        tools_invoked=tools_invoked,
        confidence_score=1.0,
        node_count=4,
    )
