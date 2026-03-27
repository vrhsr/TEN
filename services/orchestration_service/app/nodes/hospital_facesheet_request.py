"""
Node: Hospital Facesheet Request

Manages the fax outreach cadence to the hospital:
  Attempt 1 → send fax → wait 24h
  Attempt 2 → send fax → wait 48h
  Attempt 3 → send fax → wait 7 days
  After 3 attempts → escalate to coordinator queue

Also handles the HOSPITAL_FACESHEET_DOWNLOAD_QUEUE state, where a human
has been assigned to retrieve the facesheet from the hospital EMR directly.
"""
from __future__ import annotations

from shared.config import get_settings
from shared.constants import (
    FACT_SCOPE_OUTREACH,
    HANDLER_HOSPITAL_FACESHEET_REQUEST,
    STATE_FACESHEET_NOT_RECEIVED_COORDINATOR_QUEUE,
    STATE_HOSPITAL_FACESHEET_FAX_QUEUE,
    STATE_HOSPITAL_FACESHEET_DOWNLOAD_QUEUE,
    TASK_OPEN,
)
from shared.logging import get_logger
from .common import build_result, iso_offset

import time

log = get_logger(__name__)


def run_hospital_facesheet_request(state: dict, tools_client) -> dict:
    case = state["case"]
    case_id = case["case_id"]
    patient_id = case["patient_id"]
    facility_id = case.get("facility_id")
    current_state = case["state_code"]
    settings = get_settings()
    tools_invoked: list[str] = []
    node_start = time.time()

    log.info("node.face_req.start", case_id=case_id, patient_id=patient_id, node="hospital_facesheet_request")

    # ── Direct EMR download queue: human task, just normalize and wait ────────
    if current_state == STATE_HOSPITAL_FACESHEET_DOWNLOAD_QUEUE:
        open_tasks = case.get("open_tasks") or []
        dl_task = next(
            (t for t in open_tasks if t.get("task_type") == "HOSPITAL_FACESHEET_DOWNLOAD"), None
        )
        if dl_task:
            node_ms = round((time.time() - node_start) * 1000)
            log.info(
                "node.face_req.DECISION",
                case_id=case_id,
                routing_decision="WAIT_FOR_DOWNLOAD",
                next_state=STATE_HOSPITAL_FACESHEET_DOWNLOAD_QUEUE,
                duration_ms=node_ms,
                node="hospital_facesheet_request",
            )
            return build_result(
                state, HANDLER_HOSPITAL_FACESHEET_REQUEST,
                next_state=STATE_HOSPITAL_FACESHEET_DOWNLOAD_QUEUE,
                next_wake_at=iso_offset(hours=4),
                outcome_code="WAITING_FOR_DOWNLOAD_TASK",
                note="Facesheet download task is open; awaiting human agent completion",
                tools_invoked=tools_invoked,
                node_count=1,
            )
        
        node_ms = round((time.time() - node_start) * 1000)
        log.info(
            "node.face_req.DECISION",
            case_id=case_id,
            routing_decision="DOWNLOAD_FALLBACK",
            next_state=STATE_HOSPITAL_FACESHEET_FAX_QUEUE,
            duration_ms=node_ms,
            node="hospital_facesheet_request",
        )
        return build_result(
            state, HANDLER_HOSPITAL_FACESHEET_REQUEST,
            next_state=STATE_HOSPITAL_FACESHEET_FAX_QUEUE,
            outcome_code="DOWNLOAD_TASK_NOT_FOUND_FALLBACK",
            note="Download task not found; transitioning to fax path",
            tools_invoked=tools_invoked,
            node_count=1,
        )

    # ── Fax outreach path ─────────────────────────────────────────────────────
    facility_info = {}
    if facility_id:
        facility_info = tools_client.get_facility(facility_id) or {}
        tools_invoked.append("get_facility")

    facility_fax = facility_info.get("fax")
    facility_name = facility_info.get("facility_name", f"Facility {facility_id}")

    # ── Determine current attempt ─────────────────────────────────────────────
    open_tasks = case.get("open_tasks") or []
    fax_task = next(
        (t for t in open_tasks if t.get("task_type") == "HOSPITAL_FACESHEET_REQUEST"), None
    )
    attempt = 1
    task_id = None
    if fax_task:
        attempt = (fax_task.get("attempt_count") or 0) + 1
        task_id = fax_task.get("task_id")

    max_attempts = settings.facesheet_max_attempts

    # ── Escalate after max attempts ───────────────────────────────────────────
    if attempt > max_attempts:
        if task_id:
            tools_client.update_task(task_id, {
                "state_code": "DONE",
                "close_reason_code": "ESCALATED",
                "result_json": {"reason": "Max facesheet request attempts exhausted"},
            })
            tools_invoked.append(f"update_task:{task_id}")

        tools_client.create_task({
            "case_id": case_id,
            "task_type": "FACESHEET_NOT_RECEIVED_COORDINATOR",
            "intent_key": f"FACE_COORD:{case_id}",
            "state_code": TASK_OPEN,
            "queue_id": STATE_FACESHEET_NOT_RECEIVED_COORDINATOR_QUEUE,
            "handler_key": "DEMO_FACESHEET_COORDINATOR",
            "priority_rank": 15,
            "payload_json": {
                "facility_id": facility_id,
                "facility_name": facility_name,
                "facility_fax": facility_fax,
                "patient_id": patient_id,
                "attempts_made": attempt - 1,
                "instructions": (
                    f"Hospital facesheet not received after {attempt - 1} fax attempts to "
                    f"{facility_name}. Coordinator should contact the facility directly."
                ),
            },
        })
        tools_invoked.append("create_task:FACESHEET_COORDINATOR")

        node_ms = round((time.time() - node_start) * 1000)
        log.info(
            "node.face_req.DECISION",
            case_id=case_id,
            routing_decision="MAX_ATTEMPTS_ESCALATE",
            next_state=STATE_FACESHEET_NOT_RECEIVED_COORDINATOR_QUEUE,
            duration_ms=node_ms,
            node="hospital_facesheet_request",
        )
        return build_result(
            state, HANDLER_HOSPITAL_FACESHEET_REQUEST,
            next_state=STATE_FACESHEET_NOT_RECEIVED_COORDINATOR_QUEUE,
            outcome_code="FACESHEET_ESCALATED",
            note=f"No facesheet after {attempt - 1} attempts; escalated to coordinator",
            tools_invoked=tools_invoked,
            confidence_score=0.7,
            node_count=1,
        )

    # ── Send fax ──────────────────────────────────────────────────────────────
    _send_fax_request(tools_client, case_id, patient_id, facility_id, facility_fax, facility_name, attempt, tools_invoked)

    # ── Schedule next wake ────────────────────────────────────────────────────
    if attempt == 1:
        next_wake = iso_offset(hours=settings.facesheet_first_attempt_wait_hours)
    elif attempt == 2:
        next_wake = iso_offset(hours=settings.facesheet_second_attempt_wait_hours)
    else:
        next_wake = iso_offset(days=settings.facesheet_third_attempt_wait_days)

    # ── Update or create fax task ─────────────────────────────────────────────
    if task_id:
        tools_client.update_task(task_id, {
            "attempt_count": attempt,
            "next_action_at": next_wake,
        })
        tools_invoked.append(f"update_task:{task_id}")
    else:
        tools_client.create_task({
            "case_id": case_id,
            "task_type": "HOSPITAL_FACESHEET_REQUEST",
            "intent_key": f"FACE_FAX:{case_id}",
            "state_code": TASK_OPEN,
            "queue_id": STATE_HOSPITAL_FACESHEET_FAX_QUEUE,
            "handler_key": "DEMO_HOSPITAL_FACESHEET_REQUEST",
            "attempt_count": attempt,
            "next_action_at": next_wake,
            "payload_json": {
                "facility_id": facility_id,
                "facility_fax": facility_fax,
                "facility_name": facility_name,
                "patient_id": patient_id,
                "attempt": attempt,
            },
        })
        tools_invoked.append("create_task:HOSPITAL_FACESHEET_REQUEST")

    tools_client.create_fact({
        "case_id": case_id,
        "fact_scope": FACT_SCOPE_OUTREACH,
        "fact_key": f"facesheet_fax_attempt_{attempt}",
        "fact_value_str": "SENT",
        "source_system": "FAX",
        "confidence_score": 1.0,
        "is_current": True,
    })
    tools_invoked.append("create_fact:facesheet_fax_attempt")

    node_ms = round((time.time() - node_start) * 1000)
    log.info(
        "node.face_req.DECISION",
        case_id=case_id,
        routing_decision="FAX_SENT",
        next_state=STATE_HOSPITAL_FACESHEET_FAX_QUEUE,
        duration_ms=node_ms,
        node="hospital_facesheet_request",
    )
    return build_result(
        state, HANDLER_HOSPITAL_FACESHEET_REQUEST,
        next_state=STATE_HOSPITAL_FACESHEET_FAX_QUEUE,
        next_wake_at=next_wake,
        outcome_code=f"FAX_SENT_ATTEMPT_{attempt}",
        note=f"Facesheet fax request attempt {attempt} sent to {facility_name}",
        tools_invoked=tools_invoked,
        confidence_score=0.85,
        facts_considered={
            "attempt": attempt,
            "facility_fax_available": bool(facility_fax),
            "facility_id": facility_id,
        },
        node_count=1,
    )


def _send_fax_request(
    tools_client,
    case_id: int,
    patient_id: int,
    facility_id: int | None,
    facility_fax: str | None,
    facility_name: str,
    attempt: int,
    tools_invoked: list[str],
) -> None:
    """
    Send a fax to the hospital requesting the patient facesheet.
    Wire this to your fax provider (RingCentral, eFax, etc.) via the Tools layer.
    """
    if not facility_fax:
        log.warning(
            "facesheet_request.no_fax_number",
            case_id=case_id,
            facility_id=facility_id,
        )
        return
    try:
        tools_client.send_fax(
            fax_number=facility_fax,
            facility_name=facility_name,
            patient_id=patient_id,
            case_id=case_id,
            attempt=attempt,
        )
        tools_invoked.append(f"send_fax:attempt_{attempt}")
    except Exception as exc:
        log.warning(
            "facesheet_request.fax_send_failed",
            case_id=case_id,
            facility_fax=facility_fax,
            attempt=attempt,
            error=str(exc),
        )
