"""
Node: Verify Registration Information

Runs when the case is in VERIFY_REGISTRATION_INFO_QUEUE.
This state is reached after a document (insurance card, facesheet) has been
received and uploaded to S3.

The handler checks whether the human review task has been completed and
what result was recorded, then routes accordingly:
  - Task result CONFIRMED → ELIGIBILITY_VERIFICATION_QUEUE
  - Task result REJECTED / IMAGE_MISMATCH → FIX_ELIGIBILITY_ERROR_QUEUE
  - Task still open → stay in queue and re-wake in 1h
"""
from __future__ import annotations

from shared.constants import (
    HANDLER_VERIFY_REGISTRATION,
    STATE_ELIGIBILITY_VERIFICATION_QUEUE,
    STATE_FIX_ELIGIBILITY_ERROR_QUEUE,
    STATE_VERIFY_REGISTRATION_INFO_QUEUE,
)
from shared.logging import get_logger
from .common import build_result, iso_offset

import time

log = get_logger(__name__)


def run_verify_registration(state: dict, tools_client) -> dict:
    case = state["case"]
    case_id = case["case_id"]
    tools_invoked: list[str] = []
    node_start = time.time()

    log.info("node.verify_reg.start", case_id=case_id, node="verify_registration")

    open_tasks = case.get("open_tasks") or []
    verify_task = next(
        (t for t in open_tasks if t.get("task_type") == "VERIFY_REGISTRATION_INFO"), None
    )

    if verify_task:
        # Task is still open — human hasn't completed yet
        node_ms = round((time.time() - node_start) * 1000)
        log.info(
            "node.verify_reg.DECISION",
            case_id=case_id,
            routing_decision="WAITING",
            next_state=STATE_VERIFY_REGISTRATION_INFO_QUEUE,
            duration_ms=node_ms,
            node="verify_registration",
        )
        return build_result(
            state, HANDLER_VERIFY_REGISTRATION,
            next_state=STATE_VERIFY_REGISTRATION_INFO_QUEUE,
            next_wake_at=iso_offset(hours=1),
            outcome_code="WAITING_FOR_HUMAN_REVIEW",
            note="Verification task is open; awaiting human agent decision",
            tools_invoked=tools_invoked,
            node_count=1,
        )

    # No open verify task — check facts for the outcome the human recorded
    facts = case.get("facts") or {}
    verify_outcome = facts.get("verify_registration_outcome")

    if verify_outcome == "CONFIRMED":
        node_ms = round((time.time() - node_start) * 1000)
        log.info(
            "node.verify_reg.DECISION",
            case_id=case_id,
            routing_decision="CONFIRMED",
            next_state=STATE_ELIGIBILITY_VERIFICATION_QUEUE,
            duration_ms=node_ms,
            node="verify_registration",
        )
        return build_result(
            state, HANDLER_VERIFY_REGISTRATION,
            next_state=STATE_ELIGIBILITY_VERIFICATION_QUEUE,
            outcome_code="REGISTRATION_CONFIRMED",
            note="Human agent confirmed document is correct; advancing to eligibility",
            tools_invoked=tools_invoked,
            confidence_score=1.0,
            node_count=1,
        )

    if verify_outcome in ("REJECTED", "IMAGE_MISMATCH", "WRONG_PATIENT"):
        node_ms = round((time.time() - node_start) * 1000)
        log.info(
            "node.verify_reg.DECISION",
            case_id=case_id,
            routing_decision="REJECTED",
            next_state=STATE_FIX_ELIGIBILITY_ERROR_QUEUE,
            duration_ms=node_ms,
            node="verify_registration",
        )
        return build_result(
            state, HANDLER_VERIFY_REGISTRATION,
            next_state=STATE_FIX_ELIGIBILITY_ERROR_QUEUE,
            outcome_code="REGISTRATION_REJECTED",
            note=f"Document rejected by human agent: {verify_outcome}. Routed to fix queue.",
            tools_invoked=tools_invoked,
            confidence_score=1.0,
            node_count=1,
        )

    node_ms = round((time.time() - node_start) * 1000)
    log.info(
        "node.verify_reg.DECISION",
        case_id=case_id,
        routing_decision="OUTCOME_PENDING",
        next_state=STATE_VERIFY_REGISTRATION_INFO_QUEUE,
        duration_ms=node_ms,
        node="verify_registration",
    )
    # No outcome recorded yet — task was likely just created; wait
    return build_result(
        state, HANDLER_VERIFY_REGISTRATION,
        next_state=STATE_VERIFY_REGISTRATION_INFO_QUEUE,
        next_wake_at=iso_offset(hours=2),
        outcome_code="OUTCOME_PENDING",
        note="No verification outcome fact found; re-checking in 2 hours",
        tools_invoked=tools_invoked,
        node_count=1,
    )
