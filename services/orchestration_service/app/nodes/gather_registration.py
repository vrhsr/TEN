"""
Node: Gather Patient Registration Information

Runs when the case is in START_REGISTRATION_QUEUE.
Determines how to acquire the missing registration document:
  1. Insurance image already in claims → VERIFY_REGISTRATION_INFO_QUEUE
  2. Facility place of service + direct EMR → HOSPITAL_FACESHEET_DOWNLOAD_QUEUE
  3. Facility place of service + no direct EMR → parallel SELF_REG + FAX tasks
  4. Clinic place of service → CLINIC_INSURANCE_IMAGE_DOWNLOAD_QUEUE
  5. Clinic, no image found → SELF_REGISTRATION_QUEUE
"""
from __future__ import annotations

from shared.constants import (
    FACT_SCOPE_DOCUMENT,
    HANDLER_GATHER_REGISTRATION,
    STATE_CLINIC_INSURANCE_IMAGE_DOWNLOAD_QUEUE,
    STATE_HOSPITAL_FACESHEET_DOWNLOAD_QUEUE,
    STATE_HOSPITAL_FACESHEET_FAX_QUEUE,
    STATE_SELF_REGISTRATION_QUEUE,
    STATE_VERIFY_REGISTRATION_INFO_QUEUE,
    TASK_OPEN,
)
from shared.logging import get_logger
from .common import build_result, iso_offset

import time

log = get_logger(__name__)


def run_gather_registration(state: dict, tools_client, profile_client) -> dict:
    case = state["case"]
    case_id = case["case_id"]
    patient_id = case["patient_id"]
    clinic_id = case.get("clinic_id")
    facility_id = case.get("facility_id")
    tools_invoked: list[str] = []
    node_start = time.time()

    log.info("node.gather_reg.start", case_id=case_id, patient_id=patient_id, node="gather_registration")

    # ── 1. Check if claims system already has an insurance image ──────────────
    image_check = tools_client.has_insurance_image(patient_id=patient_id, clinic_id=clinic_id)
    tools_invoked.append("has_insurance_image")

    if image_check.get("has_insurance_image"):
        tools_client.create_task({
            "case_id": case_id,
            "task_type": "VERIFY_REGISTRATION_INFO",
            "intent_key": f"VERIFY_REG:{case_id}",
            "state_code": TASK_OPEN,
            "queue_id": STATE_VERIFY_REGISTRATION_INFO_QUEUE,
            "handler_key": "DEMO_VERIFY_REGISTRATION",
            "priority_rank": 50,
            "payload_json": {
                "patient_id": patient_id,
                "source": "CLAIMS_SYSTEM",
                "instructions": (
                    "Verify the insurance image already on file is the correct "
                    "document for this patient before advancing to eligibility."
                ),
            },
        })
        tools_invoked.append("create_task:VERIFY_REGISTRATION_INFO")
        
        node_ms = round((time.time() - node_start) * 1000)
        log.info(
            "node.gather_reg.DECISION",
            case_id=case_id,
            routing_decision="IMAGE_FOUND",
            next_state=STATE_VERIFY_REGISTRATION_INFO_QUEUE,
            duration_ms=node_ms,
            node="gather_registration",
        )
        return build_result(
            state,
            HANDLER_GATHER_REGISTRATION,
            next_state=STATE_VERIFY_REGISTRATION_INFO_QUEUE,
            outcome_code="IMAGE_FOUND_IN_CLAIMS",
            note="Existing insurance image routed to verification queue",
            tools_invoked=tools_invoked,
            facts_considered={"source": "claims_system", "facility_id": facility_id},
            node_count=1,
        )

    # ── 2. Facility / hospital path ────────────────────────────────────────────
    if facility_id:
        emr = profile_client.get_emr_access(
            facility_id=facility_id,
            clinic_id=clinic_id,
        )
        tools_invoked.append("profile_engine.get_emr_access")

        if emr.get("has_direct_emr_access"):
            # ── 2a. Direct EMR access ─────────────────────────────────────────
            tools_client.create_task({
                "case_id": case_id,
                "task_type": "HOSPITAL_FACESHEET_DOWNLOAD",
                "intent_key": f"FACE_DL:{case_id}",
                "state_code": TASK_OPEN,
                "queue_id": STATE_HOSPITAL_FACESHEET_DOWNLOAD_QUEUE,
                "handler_key": "DEMO_HOSPITAL_FACESHEET_DOWNLOAD",
                "priority_rank": 30,
                "payload_json": {
                    "facility_id": facility_id,
                    "patient_id": patient_id,
                    "emr_system": emr.get("emr_system"),
                    "instructions": (
                        f"Download facesheet from {emr.get('emr_system', 'facility EMR')} "
                        "and upload to the patient record."
                    ),
                },
            })
            tools_invoked.append("create_task:HOSPITAL_FACESHEET_DOWNLOAD")
            
            node_ms = round((time.time() - node_start) * 1000)
            log.info(
                "node.gather_reg.DECISION",
                case_id=case_id,
                routing_decision="DIRECT_EMR",
                next_state=STATE_HOSPITAL_FACESHEET_DOWNLOAD_QUEUE,
                duration_ms=node_ms,
                node="gather_registration",
            )
            return build_result(
                state,
                HANDLER_GATHER_REGISTRATION,
                next_state=STATE_HOSPITAL_FACESHEET_DOWNLOAD_QUEUE,
                outcome_code="DIRECT_EMR_TASK_CREATED",
                note=f"Hospital facesheet download task created for {emr.get('emr_system')}",
                tools_invoked=tools_invoked,
                facts_considered={"emr_system": emr.get("emr_system"), "facility_id": facility_id},
                node_count=1,
            )

        # ── 2b. No direct EMR — parallel: self-reg + fax ─────────────────────
        # Get facility fax for the fax task payload
        facility_info = tools_client.get_facility(facility_id) or {}
        tools_invoked.append("get_facility")

        tools_client.create_task({
            "case_id": case_id,
            "task_type": "SELF_REGISTRATION",
            "intent_key": f"SELF_REG:{case_id}",
            "state_code": TASK_OPEN,
            "queue_id": STATE_SELF_REGISTRATION_QUEUE,
            "handler_key": "DEMO_SELF_REGISTRATION",
            "priority_rank": 50,
            "payload_json": {"patient_id": patient_id, "attempt": 1},
        })
        tools_invoked.append("create_task:SELF_REGISTRATION")

        tools_client.create_task({
            "case_id": case_id,
            "task_type": "HOSPITAL_FACESHEET_REQUEST",
            "intent_key": f"FACE_FAX:{case_id}",
            "state_code": TASK_OPEN,
            "queue_id": STATE_HOSPITAL_FACESHEET_FAX_QUEUE,
            "handler_key": "DEMO_HOSPITAL_FACESHEET_REQUEST",
            "priority_rank": 40,
            "payload_json": {
                "facility_id": facility_id,
                "patient_id": patient_id,
                "facility_fax": facility_info.get("fax"),
                "facility_name": facility_info.get("facility_name"),
                "attempt": 1,
            },
        })
        tools_invoked.append("create_task:HOSPITAL_FACESHEET_FAX")

        node_ms = round((time.time() - node_start) * 1000)
        log.info(
            "node.gather_reg.DECISION",
            case_id=case_id,
            routing_decision="PARALLEL_OUTREACH",
            next_state=STATE_HOSPITAL_FACESHEET_FAX_QUEUE,
            duration_ms=node_ms,
            node="gather_registration",
        )
        return build_result(
            state,
            HANDLER_GATHER_REGISTRATION,
            next_state=STATE_HOSPITAL_FACESHEET_FAX_QUEUE,
            next_wake_at=iso_offset(hours=24),
            outcome_code="PARALLEL_OUTREACH_STARTED",
            note="No direct EMR; self-registration and fax outreach started in parallel",
            tools_invoked=tools_invoked,
            facts_considered={
                "has_direct_emr_access": False,
                "facility_id": facility_id,
                "facility_fax_available": bool(facility_info.get("fax")),
            },
            node_count=1,
        )

    # ── 3. Clinic path ─────────────────────────────────────────────────────────
    tools_client.create_task({
        "case_id": case_id,
        "task_type": "CLINIC_INSURANCE_IMAGE_DOWNLOAD",
        "intent_key": f"CLINIC_IMG:{case_id}",
        "state_code": TASK_OPEN,
        "queue_id": STATE_CLINIC_INSURANCE_IMAGE_DOWNLOAD_QUEUE,
        "handler_key": "DEMO_CLINIC_INSURANCE_IMAGE_DOWNLOAD",
        "priority_rank": 50,
        "payload_json": {
            "clinic_id": clinic_id,
            "patient_id": patient_id,
            "instructions": (
                "Check clinic EMR for insurance card image. "
                "Upload found image to S3 and register via POST /v1/documents. "
                "If not found, close this task and signal SELF_REGISTRATION."
            ),
        },
    })
    tools_invoked.append("create_task:CLINIC_INSURANCE_IMAGE_DOWNLOAD")

    node_ms = round((time.time() - node_start) * 1000)
    log.info(
        "node.gather_reg.DECISION",
        case_id=case_id,
        routing_decision="CLINIC_IMAGE",
        next_state=STATE_CLINIC_INSURANCE_IMAGE_DOWNLOAD_QUEUE,
        duration_ms=node_ms,
        node="gather_registration",
    )
    return build_result(
        state,
        HANDLER_GATHER_REGISTRATION,
        next_state=STATE_CLINIC_INSURANCE_IMAGE_DOWNLOAD_QUEUE,
        next_wake_at=iso_offset(hours=4),
        outcome_code="CLINIC_IMAGE_TASK_CREATED",
        note="Clinic place of service; assigned to clinic insurance image download queue",
        tools_invoked=tools_invoked,
        facts_considered={"clinic_id": clinic_id, "has_facility": False},
        node_count=1,
    )
