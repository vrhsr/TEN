"""
Node: Self Registration

Manages the timed outreach cadence to the patient:
  Attempt 1 → send SMS/voice → wait 24h
  Attempt 2 → send SMS/voice → wait 48h
  Attempt 3 → send SMS/voice → wait 7 days
  After 3 attempts → escalate to coordinator queue

Each advance_case call that lands here increments the attempt and schedules
the next wake_at.  The actual SMS/voice send is a best-effort side effect;
failures are logged but do not block the case.
"""
from __future__ import annotations

from shared.config import get_settings
from shared.constants import (
    FACT_SCOPE_OUTREACH,
    HANDLER_SELF_REGISTRATION,
    STATE_SELF_REGISTRATION_NOT_RECEIVED_COORDINATOR_QUEUE,
    STATE_SELF_REGISTRATION_QUEUE,
    TASK_OPEN,
)
from shared.logging import get_logger
from .common import build_result, iso_offset

import time

log = get_logger(__name__)


def run_self_registration(state: dict, tools_client) -> dict:
    case = state["case"]
    case_id = case["case_id"]
    patient_id = case["patient_id"]
    settings = get_settings()
    tools_invoked: list[str] = []
    node_start = time.time()

    log.info("node.self_reg.start", case_id=case_id, patient_id=patient_id, node="self_registration")

    # ── Load patient ──────────────────────────────────────────────────────────
    patient = tools_client.get_patient(patient_id)
    tools_invoked.append("get_patient")

    if not patient:
        log.error("node.self_reg.error", case_id=case_id, error="Patient not found", node="self_registration")
        return build_result(
            state, HANDLER_SELF_REGISTRATION,
            next_state=STATE_SELF_REGISTRATION_NOT_RECEIVED_COORDINATOR_QUEUE,
            outcome_code="PATIENT_NOT_FOUND",
            note="Patient not found; escalating to coordinator",
            tools_invoked=tools_invoked,
            node_count=1,
        )

    # Deceased or no contact → skip outreach immediately
    if patient.get("is_deceased"):
        node_ms = round((time.time() - node_start) * 1000)
        log.info(
            "node.self_reg.DECISION",
            case_id=case_id,
            routing_decision="SKIP_DECEASED",
            next_state=STATE_SELF_REGISTRATION_NOT_RECEIVED_COORDINATOR_QUEUE,
            duration_ms=node_ms,
            node="self_registration",
        )
        return build_result(
            state, HANDLER_SELF_REGISTRATION,
            next_state=STATE_SELF_REGISTRATION_NOT_RECEIVED_COORDINATOR_QUEUE,
            outcome_code="PATIENT_DECEASED",
            note="Patient is marked deceased; skipping self-registration outreach",
            tools_invoked=tools_invoked,
            node_count=1,
        )

    phone = patient.get("mobile") or patient.get("phone")
    if not phone:
        node_ms = round((time.time() - node_start) * 1000)
        log.info(
            "node.self_reg.DECISION",
            case_id=case_id,
            routing_decision="NO_PHONE_ESCALATE",
            next_state=STATE_SELF_REGISTRATION_NOT_RECEIVED_COORDINATOR_QUEUE,
            duration_ms=node_ms,
            node="self_registration",
        )
        return build_result(
            state, HANDLER_SELF_REGISTRATION,
            next_state=STATE_SELF_REGISTRATION_NOT_RECEIVED_COORDINATOR_QUEUE,
            outcome_code="NO_CONTACT_INFO",
            note="No phone number available for patient outreach",
            tools_invoked=tools_invoked,
            node_count=1,
        )

    # ── Determine current attempt from the open SELF_REG task ─────────────────
    open_tasks = case.get("open_tasks") or []
    self_reg_task = next(
        (t for t in open_tasks if t.get("task_type") == "SELF_REGISTRATION"), None
    )
    attempt = 1
    task_id = None
    if self_reg_task:
        attempt = (self_reg_task.get("attempt_count") or 0) + 1
        task_id = self_reg_task.get("task_id")

    max_attempts = settings.self_reg_max_attempts

    # ── Escalate after max attempts ───────────────────────────────────────────
    if attempt > max_attempts:
        if task_id:
            tools_client.update_task(task_id, {
                "state_code": "DONE",
                "close_reason_code": "ESCALATED",
                "result_json": {"reason": "Max self-registration attempts exhausted"},
            })
            tools_invoked.append(f"update_task:{task_id}")

        tools_client.create_task({
            "case_id": case_id,
            "task_type": "SELF_REGISTRATION_COORDINATOR",
            "intent_key": f"SELF_REG_COORD:{case_id}",
            "state_code": TASK_OPEN,
            "queue_id": STATE_SELF_REGISTRATION_NOT_RECEIVED_COORDINATOR_QUEUE,
            "handler_key": "DEMO_SELF_REG_COORDINATOR",
            "priority_rank": 20,
            "payload_json": {
                "patient_id": patient_id,
                "phone": phone,
                "attempts_made": attempt - 1,
                "instructions": (
                    "Patient did not respond to 3 self-registration attempts. "
                    "Coordinator should manually contact patient to obtain insurance information."
                ),
            },
        })
        tools_invoked.append("create_task:SELF_REG_COORDINATOR")

        node_ms = round((time.time() - node_start) * 1000)
        log.info(
            "node.self_reg.DECISION",
            case_id=case_id,
            routing_decision="MAX_ATTEMPTS_ESCALATE",
            next_state=STATE_SELF_REGISTRATION_NOT_RECEIVED_COORDINATOR_QUEUE,
            duration_ms=node_ms,
            node="self_registration",
        )
        return build_result(
            state, HANDLER_SELF_REGISTRATION,
            next_state=STATE_SELF_REGISTRATION_NOT_RECEIVED_COORDINATOR_QUEUE,
            outcome_code="SELF_REG_ESCALATED",
            note=f"No response after {attempt - 1} attempts; escalated to coordinator",
            tools_invoked=tools_invoked,
            confidence_score=0.7,
            node_count=1,
        )

    # ── Send outreach ─────────────────────────────────────────────────────────
    _send_outreach(tools_client, patient, case_id, attempt, tools_invoked)

    # ── Schedule next wake ────────────────────────────────────────────────────
    if attempt == 1:
        next_wake = iso_offset(hours=settings.self_reg_first_attempt_wait_hours)
    elif attempt == 2:
        next_wake = iso_offset(hours=settings.self_reg_second_attempt_wait_hours)
    else:
        next_wake = iso_offset(days=settings.self_reg_third_attempt_wait_days)

    # ── Update or create the SELF_REG task with new attempt count ────────────
    if task_id:
        tools_client.update_task(task_id, {
            "attempt_count": attempt,
            "next_action_at": next_wake,
            "payload_json": {**((self_reg_task or {}).get("payload_json") or {}), "attempt": attempt},
        })
        tools_invoked.append(f"update_task:{task_id}")
    else:
        tools_client.create_task({
            "case_id": case_id,
            "task_type": "SELF_REGISTRATION",
            "intent_key": f"SELF_REG:{case_id}",
            "state_code": TASK_OPEN,
            "queue_id": STATE_SELF_REGISTRATION_QUEUE,
            "handler_key": "DEMO_SELF_REGISTRATION",
            "attempt_count": attempt,
            "next_action_at": next_wake,
            "payload_json": {"patient_id": patient_id, "attempt": attempt},
        })
        tools_invoked.append("create_task:SELF_REGISTRATION")

    tools_client.create_fact({
        "case_id": case_id,
        "fact_scope": FACT_SCOPE_OUTREACH,
        "fact_key": f"self_reg_attempt_{attempt}",
        "fact_value_str": "SENT",
        "source_system": "OUTREACH",
        "confidence_score": 1.0,
        "is_current": True,
    })
    tools_invoked.append("create_fact:self_reg_attempt")

    node_ms = round((time.time() - node_start) * 1000)
    log.info(
        "node.self_reg.DECISION",
        case_id=case_id,
        routing_decision="OUTREACH_SENT",
        next_state=STATE_SELF_REGISTRATION_QUEUE,
        duration_ms=node_ms,
        node="self_registration",
    )
    return build_result(
        state, HANDLER_SELF_REGISTRATION,
        next_state=STATE_SELF_REGISTRATION_QUEUE,
        next_wake_at=next_wake,
        outcome_code=f"OUTREACH_SENT_ATTEMPT_{attempt}",
        note=f"Self-registration outreach attempt {attempt} sent; waiting for patient response",
        tools_invoked=tools_invoked,
        confidence_score=0.85,
        facts_considered={"attempt": attempt, "phone": bool(phone)},
        node_count=1,
    )


def _send_outreach(
    tools_client,
    patient: dict,
    case_id: int,
    attempt: int,
    tools_invoked: list[str],
) -> None:
    """
    Trigger SMS/voice outreach. The messaging endpoint is a stub here;
    wire to your communication platform (Twilio, RingCentral, etc.)
    via the Tools layer when ready.
    """
    phone = patient.get("mobile") or patient.get("phone")
    try:
        tools_client.send_sms(
            phone=phone,
            message=(
                f"We need your insurance information to process "
                f"your recent medical visit. Please reply or call us. (Attempt {attempt}/3)"
            ),
            case_id=case_id,
            attempt=attempt,
        )
        tools_invoked.append(f"send_sms:attempt_{attempt}")
    except Exception as exc:
        log.warning(
            "self_registration.sms_send_failed",
            case_id=case_id,
            attempt=attempt,
            error=str(exc),
        )
