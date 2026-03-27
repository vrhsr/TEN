"""
Node: Initialize Demographics Flow
Handler: DEMO_INITIALIZE

Node 1 — Fetch Patient Facts
    • Accepts task_id from the LangGraph state (injected by FastAPI trigger).
    • Fetches patient demographics + insurance from the Claims system API.
    • Falls back to RCM_FACTS if the Claims API is unavailable.

Node 2 — Check Duplicate
    • Calls the duplicate-check endpoint with first_name, last_name, dob, patient_id.
    • If duplicates found → IMMEDIATELY routes to CASE_CLOSED_DUPLICATE (Close Out Node).
      Stores duplicate payload (outcome = "DUPLICATE_PATIENT") in RCM_FACTS.
      Skips all remaining nodes (Verify Demo & Insurance, Registration, etc.).
    • If no duplicates → continues to Node 3.

Node 3 — Verify Demo & Insurance
    • 3a: Self-pay check → CASE_CLOSED_SELF_PAY
    • 3b: Demographics + insurance + verified < 30 days → CASE_READY_FOR_CLAIM_CREATION
    • 3c: Demographics + insurance + stale → ELIGIBILITY_VERIFICATION_QUEUE
    • 3d: Missing demographics/insurance + hospital → START_REGISTRATION_QUEUE
    • 3e: Missing demographics/insurance + clinic → CHECK_INS_IN_CLINIC_EMR

All Tools API calls are idempotent — re-running this node on the same case is safe.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta

from shared.config import get_settings
from shared.constants import (
    FACT_SCOPE_DEMOGRAPHICS,
    FACT_SCOPE_DUPLICATE,
    HANDLER_INITIALIZE,
    STATE_CASE_CLOSED_DUPLICATE,
    STATE_CASE_CLOSED_SELF_PAY,
    STATE_CASE_READY_FOR_CLAIM_CREATION,
    STATE_ELIGIBILITY_VERIFICATION_QUEUE,
    STATE_START_REGISTRATION_QUEUE,
    TASK_OPEN,
)
from shared.logging import get_logger
from .common import (
    build_result,
    get_primary_insurance,
    is_demographics_complete,
    is_insurance_present,
    iso_offset,
)

log = get_logger(__name__)


def run_initialize(state: dict, tools_client) -> dict:
    """
    Entry-point for the CLAIM_INITIALIZE state.

    Decision tree executed across 3 logical nodes:
      Node 1: Fetch patient + insurance facts
      Node 2: Duplicate patient check → CASE_CLOSED_DUPLICATE [EXIT if found]
      Node 3: Verify Demo & Insurance:
        3a) Self-pay → CASE_CLOSED_SELF_PAY
        3b) Complete + fresh → CASE_READY_FOR_CLAIM_CREATION
        3c) Complete + stale → ELIGIBILITY_VERIFICATION_QUEUE
        3d) Incomplete + hospital → START_REGISTRATION_QUEUE
        3e) Incomplete + clinic → CHECK_INS_IN_CLINIC_EMR
    """
    case = state["case"]
    case_id = case["case_id"]
    patient_id = case["patient_id"]
    task_id: int | None = state.get("task_id")
    settings = get_settings()
    tools_invoked: list[str] = []

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # NODE 1 — Fetch Patient Facts
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    node1_start = time.time()
    log.info(
        "node1.fetch_facts.start",
        case_id=case_id,
        patient_id=patient_id,
        task_id=task_id,
        node="fetch_patient_facts",
    )

    # ── Fetch patient record ──────────────────────────────────────────────
    try:
        patient = tools_client.get_patient(patient_id)
        tools_invoked.append("get_patient")
    except Exception as exc:
        log.error(
            "node1.fetch_facts.get_patient_failed",
            case_id=case_id,
            patient_id=patient_id,
            error=str(exc),
            node="fetch_patient_facts",
        )
        raise

    # ── Patient not found — route to registration ─────────────────────────
    if not patient:
        node1_ms = round((time.time() - node1_start) * 1000)
        log.warning(
            "node1.fetch_facts.PATIENT_NOT_FOUND",
            case_id=case_id,
            patient_id=patient_id,
            duration_ms=node1_ms,
            node="fetch_patient_facts",
        )
        return build_result(
            state,
            HANDLER_INITIALIZE,
            next_state=STATE_START_REGISTRATION_QUEUE,
            outcome_code="PATIENT_NOT_FOUND",
            note=f"Patient {patient_id} not found in claims system",
            tools_invoked=tools_invoked,
        )

    # ── Fetch insurance records ───────────────────────────────────────────
    try:
        insurances = tools_client.get_patient_insurances(patient_id)
        tools_invoked.append("get_patient_insurances")
    except Exception as exc:
        log.error(
            "node1.fetch_facts.get_insurances_failed",
            case_id=case_id,
            patient_id=patient_id,
            error=str(exc),
            node="fetch_patient_facts",
        )
        raise

    # ── Evaluate what we have (for logging only at this stage) ────────────
    demographics_complete_check = is_demographics_complete(patient)
    has_insurance_check = is_insurance_present(insurances)
    is_self_pay_check = (
        patient.get("is_self_pay")
        or patient.get("billing_method") == 0
    )

    node1_ms = round((time.time() - node1_start) * 1000)
    log.info(
        "node1.fetch_facts.result",
        case_id=case_id,
        patient_id=patient_id,
        patient_found=True,
        insurance_count=len(insurances),
        has_demographics=demographics_complete_check,
        has_insurance=has_insurance_check,
        is_self_pay=is_self_pay_check,
        duration_ms=node1_ms,
        node="fetch_patient_facts",
    )

    # ── Build facts_considered snapshot (used for audit / step history) ────
    facts_considered: dict = {
        "task_id": task_id,
        "billing_method": patient.get("billing_method"),
        "is_deceased": patient.get("is_deceased"),
        "first_name_present": bool(patient.get("first_name")),
        "last_name_present": bool(patient.get("last_name")),
        "dob_present": bool(patient.get("dob")),
        "insurance_count": len(insurances),
    }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # NODE 2 — Check Duplicate
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    node2_start = time.time()
    log.info(
        "node2.check_duplicate.start",
        case_id=case_id,
        patient_id=patient_id,
        node="check_duplicate",
    )

    # ── Call duplicate check API ──────────────────────────────────────────
    try:
        dup_result = tools_client.duplicate_check(patient_id)
        tools_invoked.append("duplicate_check")
    except Exception as exc:
        log.error(
            "node2.check_duplicate.failed",
            case_id=case_id,
            patient_id=patient_id,
            error=str(exc),
            node="check_duplicate",
        )
        raise

    node2_ms = round((time.time() - node2_start) * 1000)

    # ── Duplicate found → skip all remaining nodes → Close Out ────────────
    if dup_result.get("has_duplicates"):
        candidates = dup_result.get("candidates", [])
        duplicate_patient_ids = [
            str(c.get("patient_id", "")) for c in candidates
        ]

        log.info(
            "node2.check_duplicate.DUPLICATE_FOUND",
            case_id=case_id,
            patient_id=patient_id,
            candidate_count=len(candidates),
            decision="SKIP_TO_CLOSE_OUT",
            duration_ms=node2_ms,
            node="check_duplicate",
        )

        # ── Store duplicate facts in RCM_FACT ─────────────────────────────
        tools_client.create_facts({
            "case_id": case_id,
            "facts": [
                {
                    "fact_scope": FACT_SCOPE_DUPLICATE,
                    "fact_key": "outcome",
                    "fact_value_str": "DUPLICATE_PATIENT",
                    "source_system": "CLAIMS_DB",
                    "confidence_score": 1.0,
                    "is_current": True,
                },
                {
                    "fact_scope": FACT_SCOPE_DUPLICATE,
                    "fact_key": "duplicate_candidate_count",
                    "fact_value_str": str(len(candidates)),
                    "source_system": "CLAIMS_DB",
                    "confidence_score": 1.0,
                    "is_current": True,
                },
                {
                    "fact_scope": FACT_SCOPE_DUPLICATE,
                    "fact_key": "duplicate_patient_ids",
                    "fact_value_str": ",".join(duplicate_patient_ids),
                    "source_system": "CLAIMS_DB",
                    "confidence_score": 1.0,
                    "is_current": True,
                },
            ],
        })
        tools_invoked.append("create_facts:DUPLICATE")

        # ── Update task payload with duplicate outcome ────────────────────
        if task_id:
            try:
                tools_client.update_task(task_id, {
                    "payload_json": {
                        "outcome": "DUPLICATE_PATIENT",
                        "duplicate_candidate_count": len(candidates),
                        "duplicate_patient_ids": duplicate_patient_ids,
                        "case_id": case_id,
                        "patient_id": patient_id,
                    }
                })
                tools_invoked.append("update_task:payload")
            except Exception as exc:
                log.warning(
                    "node2.check_duplicate.task_update_failed",
                    case_id=case_id,
                    task_id=task_id,
                    error=str(exc),
                    node="check_duplicate",
                )

        facts_considered.update({
            "duplicate_check_done": True,
            "duplicate_found": True,
            "duplicate_candidate_count": len(candidates),
        })

        # ── EXIT: Route to Close Out Node ─────────────────────────────────
        return build_result(
            state,
            HANDLER_INITIALIZE,
            next_state=STATE_CASE_CLOSED_DUPLICATE,
            outcome_code="DUPLICATE_PATIENT",
            note=(
                f"Duplicate patient detected: {len(candidates)} candidate(s). "
                "Skipping all remaining nodes. Routing to Close Out."
            ),
            facts_considered=facts_considered,
            tools_invoked=tools_invoked,
            confidence_score=1.0,
            node_count=2,
        )

    # ── No duplicate found — continue to Node 3 ──────────────────────────
    log.info(
        "node2.check_duplicate.NO_DUPLICATE",
        case_id=case_id,
        patient_id=patient_id,
        decision="CONTINUE_TO_VERIFY",
        duration_ms=node2_ms,
        node="check_duplicate",
    )

    facts_considered.update({
        "duplicate_check_done": True,
        "duplicate_found": False,
    })

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # NODE 3 — Verify Demo & Insurance
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    node3_start = time.time()
    log.info(
        "node3.verify_demo_ins.start",
        case_id=case_id,
        patient_id=patient_id,
        node="verify_demo_insurance",
    )

    # ── 3a: Self-pay check ────────────────────────────────────────────────
    is_self_pay = (
        patient.get("is_self_pay")
        or patient.get("billing_method") == 0
    )

    if is_self_pay:
        node3_ms = round((time.time() - node3_start) * 1000)

        log.info(
            "node3.verify_demo_ins.DECISION",
            case_id=case_id,
            node="verify_demo_insurance",
            routing_decision="SELF_PAY",
            next_state=STATE_CASE_CLOSED_SELF_PAY,
            is_self_pay=True,
            duration_ms=node3_ms,
            reason="Patient billing method is self-pay",
        )

        tools_client.create_facts({
            "case_id": case_id,
            "facts": [{
                "fact_scope": FACT_SCOPE_DEMOGRAPHICS,
                "fact_key": "billing_method",
                "fact_value_str": "SELF_PAY",
                "source_system": "CLAIMS_DB",
                "confidence_score": 1.0,
                "is_current": True,
            }],
        })
        tools_invoked.append("create_facts:SELF_PAY")

        facts_considered.update({
            "is_self_pay": True,
        })

        return build_result(
            state,
            HANDLER_INITIALIZE,
            next_state=STATE_CASE_CLOSED_SELF_PAY,
            outcome_code="SELF_PAY_DETECTED",
            note="Patient billing method is self-pay (BILLING_METHOD=0)",
            facts_considered=facts_considered,
            tools_invoked=tools_invoked,
            confidence_score=1.0,
            node_count=3,
        )

    # ── 3b-3e: Demographics and insurance evaluation ──────────────────────
    demographics_complete = is_demographics_complete(patient)
    has_insurance = is_insurance_present(insurances)
    primary = get_primary_insurance(insurances)
    freshness_days = settings.eligibility_freshness_days

    eligibility_check_date = (
        primary.get("eligibility_check_date") if primary else None
    )
    is_fresh = _is_freshly_verified(eligibility_check_date, freshness_days)

    facts_considered.update({
        "is_self_pay": False,
        "demographics_complete": demographics_complete,
        "has_insurance": has_insurance,
        "eligibility_freshness_days": freshness_days,
        "eligibility_check_date": eligibility_check_date,
        "is_freshly_verified": is_fresh,
    })

    node3_ms = round((time.time() - node3_start) * 1000)

    # ── 3d/3e: Missing demographics or insurance → Registration ───────────
    if not demographics_complete or not has_insurance:
        place_of_service = case.get("place_of_service", "hospital")

        if place_of_service == "clinic":
            next_state = "CHECK_INS_IN_CLINIC_EMR"
            routing_decision = "REGISTRATION_CLINIC"
        else:
            next_state = STATE_START_REGISTRATION_QUEUE
            routing_decision = "REGISTRATION_HOSPITAL"

        log.info(
            "node3.verify_demo_ins.DECISION",
            case_id=case_id,
            node="verify_demo_insurance",
            routing_decision=routing_decision,
            next_state=next_state,
            has_demographics=demographics_complete,
            has_insurance=has_insurance,
            place_of_service=place_of_service,
            duration_ms=node3_ms,
            reason="Demographics or insurance missing",
        )

        facts_considered["place_of_service"] = place_of_service

        return build_result(
            state,
            HANDLER_INITIALIZE,
            next_state=next_state,
            outcome_code="REGISTRATION_INCOMPLETE",
            note=f"Demographics or insurance missing; POS={place_of_service}",
            facts_considered=facts_considered,
            tools_invoked=tools_invoked,
            confidence_score=0.9,
            node_count=3,
        )

    # ── 3b: Fresh eligibility → Claim ready (terminal) ────────────────────
    if is_fresh:
        log.info(
            "node3.verify_demo_ins.DECISION",
            case_id=case_id,
            node="verify_demo_insurance",
            routing_decision="CLAIM_READY",
            next_state=STATE_CASE_READY_FOR_CLAIM_CREATION,
            has_demographics=True,
            has_insurance=True,
            is_freshly_verified=True,
            duration_ms=node3_ms,
            reason="Demographics complete and eligibility recently verified",
        )

        return build_result(
            state,
            HANDLER_INITIALIZE,
            next_state=STATE_CASE_READY_FOR_CLAIM_CREATION,
            outcome_code="READY_FOR_CLAIM_CREATION",
            note="Demographics complete and eligibility recently verified",
            facts_considered=facts_considered,
            tools_invoked=tools_invoked,
            confidence_score=1.0,
            node_count=3,
        )

    # ── 3c: Stale eligibility → Verification queue ────────────────────────
    log.info(
        "node3.verify_demo_ins.DECISION",
        case_id=case_id,
        node="verify_demo_insurance",
        routing_decision="ELIGIBILITY_STALE",
        next_state=STATE_ELIGIBILITY_VERIFICATION_QUEUE,
        has_demographics=True,
        has_insurance=True,
        is_freshly_verified=False,
        eligibility_check_date=eligibility_check_date,
        freshness_days=freshness_days,
        duration_ms=node3_ms,
        reason="Insurance present but eligibility not recently verified",
    )

    return build_result(
        state,
        HANDLER_INITIALIZE,
        next_state=STATE_ELIGIBILITY_VERIFICATION_QUEUE,
        outcome_code="ELIGIBILITY_STALE",
        note="Insurance present but eligibility not recently verified",
        next_wake_at=iso_offset(minutes=2),
        facts_considered=facts_considered,
        tools_invoked=tools_invoked,
        confidence_score=0.95,
        node_count=3,
    )


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _is_freshly_verified(
    check_date_str: str | None,
    freshness_days: int,
) -> bool:
    """
    Returns True if eligibility was verified within freshness_days of today.
    Returns False if check_date_str is None, empty, or unparseable.
    """
    if not check_date_str:
        return False
    try:
        check_date = datetime.strptime(
            check_date_str[:10], "%Y-%m-%d"
        ).date()
        cutoff = date.today() - timedelta(days=freshness_days)
        return check_date >= cutoff
    except (ValueError, TypeError):
        return False