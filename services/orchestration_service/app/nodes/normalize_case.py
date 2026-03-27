"""
Node: Normalize Case

Catch-all handler for states that are driven by human queue completion
or explicit signals (DOCUMENT_UPLOADED, HUMAN_REVIEW_COMPLETED, etc.).

When the orchestration engine receives an advance_case call for a case
that is sitting in a human queue, this handler records the wake event
and returns the same state so Temporal can re-sleep until the next signal.
"""
from __future__ import annotations

from shared.constants import HANDLER_NORMALIZE_CASE, TERMINAL_STATES
from shared.logging import get_logger
from .common import build_result, iso_offset

import time

log = get_logger(__name__)


def run_normalize_case(state: dict, tools_client) -> dict:
    case = state["case"]
    case_id = case["case_id"]
    current_state = case["state_code"]
    node_start = time.time()

    node_ms = round((time.time() - node_start) * 1000)

    if current_state in TERMINAL_STATES:
        log.info(
            "node.terminal.DONE",
            case_id=case_id,
            next_state=current_state,
            duration_ms=node_ms,
            node="normalize_case",
        )
        return build_result(
            state, HANDLER_NORMALIZE_CASE,
            next_state=current_state,
            outcome_code="TERMINAL_NO_OP",
            note=f"Case is in terminal state {current_state}; no action taken",
            node_count=1,
        )

    log.info(
        "node.human_queue.WAITING",
        case_id=case_id,
        next_state=current_state,
        duration_ms=node_ms,
        node="normalize_case",
    )
    return build_result(
        state, HANDLER_NORMALIZE_CASE,
        next_state=current_state,
        next_wake_at=iso_offset(hours=4),
        outcome_code="HUMAN_QUEUE_WAITING",
        note=f"Case is in human queue {current_state}; waiting for queue completion signal",
        node_count=1,
    )
