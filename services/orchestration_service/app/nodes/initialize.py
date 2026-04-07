from __future__ import annotations

import time
import uuid
from datetime import date, datetime, timedelta, timezone

from shared.logging import get_logger
from shared.constants import (
    HANDLER_INITIALIZE,
    STATE_CASE_CLOSED_DUPLICATE,
    STATE_CASE_CLOSED_SELF_PAY,
    STATE_CASE_READY_FOR_CLAIM_CREATION,
    STATE_ELIGIBILITY_VERIFICATION_QUEUE,
    STATE_START_REGISTRATION_QUEUE,
)

log = get_logger(__name__)

ELIGIBILITY_FRESHNESS_DAYS = 30
REQUIRED_DEMO_FIELDS = [
    "FIRST_NAME",
    "LAST_NAME",
    "DATE_OF_BIRTH",
    "ADDRESS_LINE1",
    "CITY",
    "STATE",
    "ZIP",
]


def run_initialize(state: dict, tools_client) -> dict:
    case = state["case"]
    case_id = case["case_id"]
    task_id = state.get("task_id")
    run_id = str(uuid.uuid4())
    flow_start = time.time()

    tools_invoked: list[str] = []
    facts_considered: dict = {}

    print(f"\n{'='*60}")
    print("   run_initialize START")
    print(f"   case_id  : {case_id}")
    print(f"   task_id  : {task_id}")
    print(f"   run_id   : {run_id}")
    print(f"{'='*60}")

    log.info(
        "initialize.start",
        task_id=task_id,
        case_id=case_id,
        handler=HANDLER_INITIALIZE,
        run_id=run_id,
    )

    # NODE 1 — Fetch Facts
    node1_start = time.time()
    node1_key = "FETCH_FACTS"

    log.info(
        "node1.fetch_facts.start",
        case_id=case_id,
        task_id=task_id,
        run_id=run_id,
    )

    try:
        facts = tools_client.get_case_facts(case_id)
        tools_invoked.append("get_case_facts")
        print(f"\n   Node 1: get_case_facts({case_id}) → {len(facts)} facts")
    except Exception as exc:
        print(f"\n   Node 1: get_case_facts FAILED → {exc}")
        log.error(
            "node1.fetch_facts.failed",
            case_id=case_id,
            error=str(exc),
        )
        raise

    patient_fact = _get_fact(facts, "PATIENT_FACT")
    insurance_fact = _get_fact(facts, "INSURANCE_FACT")
    demographics_fact = _get_fact(facts, "DEMOGRAPHICS_FACT")

    print(f"   PATIENT_FACT      : {'✅ found' if patient_fact else '❌ missing'}")
    print(f"   INSURANCE_FACT    : {'✅ found' if insurance_fact else '❌ missing'}")
    print(f"   DEMOGRAPHICS_FACT : {'✅ found' if demographics_fact else '❌ missing'}")

    log.info(
        "node1.fetch_facts.complete",
        case_id=case_id,
        total_facts=len(facts),
        has_patient_fact=patient_fact is not None,
        has_insurance_fact=insurance_fact is not None,
        has_demographics_fact=demographics_fact is not None,
        duration_ms=_ms(node1_start),
        run_id=run_id,
    )

    facts_considered.update({
        "task_id": task_id,
        "case_id": case_id,
        "clinic_id": case.get("clinic_id"),
        "patient_id": case.get("patient_id"),
        "has_patient_fact": patient_fact is not None,
        "has_insurance_fact": insurance_fact is not None,
        "has_demographics_fact": demographics_fact is not None,
        "total_facts": len(facts),
    })

    _write_node_history(
        client=tools_client,
        case_id=case_id,
        task_id=task_id,
        run_id=run_id,
        node_key=node1_key,
        node_index=1,
        duration_ms=_ms(node1_start),
        outcome_code="FACTS_LOADED",
        output_summary={
            "total_facts": len(facts),
            "has_patient_fact": patient_fact is not None,
            "has_insurance_fact": insurance_fact is not None,
            "has_demographics_fact": demographics_fact is not None,
        },
    )

    # NODE 2 — Check Duplicate
    node2_start = time.time()
    node2_key = "CHECK_DUPLICATE"

    log.info(
        "node2.check_duplicate.start",
        case_id=case_id,
        patient_id=case.get("patient_id"),
        run_id=run_id,
    )

    print("\n   Node 2: Check Duplicate")

    # ── Call duplicate check API with real patient details ────────────
    dup_payload = {
        "first_name" : patient_fact.get("FIRST_NAME") if patient_fact else None,
        "last_name"  : patient_fact.get("LAST_NAME")  if patient_fact else None,
        "dob"        : patient_fact.get("DATE_OF_BIRTH") if patient_fact else None,
        "patient_id" : case.get("patient_id"),
    }
    
    try:
        dup_result = tools_client.duplicate_check(
            dup_payload,
            clinic_id=case.get("clinic_id", 0),
            patient_id=case.get("patient_id", 0),
        )
        tools_invoked.append("duplicate_check")
        
        has_duplicates     = dup_result.get("has_duplicates", False)
        duplicate_patients = dup_result.get("candidates", [])
        
        print(f"   duplicate_check → has_duplicates={has_duplicates} ({len(duplicate_patients)} candidates)")
    except Exception as exc:
        print(f"   Node 2: duplicate_check FAILED → {exc}")
        has_duplicates = False
        duplicate_patients = []

    if has_duplicates:
        duplicate_ids = [str(d.get("patient_id", "")) for d in duplicate_patients]

        print(f"   ⚠️  DUPLICATE FOUND: {duplicate_ids}")

        duplicate_payload = {
            "outcome": "DUPLICATE_PATIENT",
            "duplicate_candidate_count": len(duplicate_patients),
            "duplicate_patient_ids": duplicate_ids,
            "case_id": case_id,
            "patient_id": case.get("patient_id"),
            "flagged_at": datetime.now(timezone.utc).isoformat(),
            "action_required": "HUMAN_REVIEW_REQUIRED",
            "instructions": (
                "Please review the duplicate patients, "
                "merge if appropriate, and restart the workflow."
            ),
        }

        if task_id:
            try:
                tools_client.update_task(task_id, duplicate_payload)
                tools_invoked.append("update_task:DUPLICATE_PAYLOAD")
            except Exception as exc:
                log.warning(
                    "node2.task_update_failed",
                    task_id=task_id,
                    error=str(exc),
                )

        facts_considered.update({
            "duplicate_check_done": True,
            "duplicate_found": True,
            "duplicate_candidate_count": len(duplicate_patients),
        })

        _write_node_history(
            client=tools_client,
            case_id=case_id,
            task_id=task_id,
            run_id=run_id,
            node_key=node2_key,
            node_index=2,
            duration_ms=_ms(node2_start),
            outcome_code="DUPLICATE_FOUND",
            output_summary={
                "next_state": "HUMAN_QUEUE",
                "duplicate_ids": duplicate_ids,
            },
        )

        return _build_result(
            case_id=case_id,
            task_id=task_id,
            next_state="HUMAN_QUEUE",
            outcome_code="DUPLICATE_PATIENT",
            note=f"Duplicate found: {len(duplicate_patients)} candidate(s).",
            facts_considered=facts_considered,
            tools_invoked=tools_invoked,
            confidence_score=1.0,
            duration_ms=_ms(flow_start),
        )

    print("   ✅ No duplicate found")

    log.info(
        "node2.check_duplicate.NO_DUPLICATE",
        case_id=case_id,
        duration_ms=_ms(node2_start),
        run_id=run_id,
    )

    facts_considered.update({
        "duplicate_check_done": True,
        "duplicate_found": False,
    })

    _write_node_history(
        client=tools_client,
        case_id=case_id,
        task_id=task_id,
        run_id=run_id,
        node_key=node2_key,
        node_index=2,
        duration_ms=_ms(node2_start),
        outcome_code="NO_DUPLICATE",
        output_summary={"duplicate_found": False},
    )

    # NODE 3 — Verify Demo & Insurance
    node3_start = time.time()
    node3_key = "VERIFY_DEMO_INSURANCE"

    print("\n   Node 3: Verify Demo & Insurance")

    log.info(
        "node3.verify_demo_ins.start",
        case_id=case_id,
        run_id=run_id,
    )

    is_self_pay = _is_self_pay(patient_fact)
    print(f"   is_self_pay          : {is_self_pay}")

    if is_self_pay:
        facts_considered.update({"is_self_pay": True})

        log.info(
            "node3.verify_demo_ins.DECISION",
            case_id=case_id,
            routing_decision="SELF_PAY",
            next_state=STATE_CASE_CLOSED_SELF_PAY,
            duration_ms=_ms(node3_start),
        )

        _write_node_history(
            client=tools_client,
            case_id=case_id,
            task_id=task_id,
            run_id=run_id,
            node_key=node3_key,
            node_index=3,
            duration_ms=_ms(node3_start),
            outcome_code="SELF_PAY_DETECTED",
            output_summary={"next_state": STATE_CASE_CLOSED_SELF_PAY},
        )

        return _build_result(
            case_id=case_id,
            task_id=task_id,
            next_state=STATE_CASE_CLOSED_SELF_PAY,
            outcome_code="SELF_PAY_DETECTED",
            note="Patient is self-pay",
            facts_considered=facts_considered,
            tools_invoked=tools_invoked,
            confidence_score=1.0,
            duration_ms=_ms(flow_start),
        )

    demographics_complete = _is_demographics_complete(demographics_fact)
    has_insurance = insurance_fact is not None
    eligibility_check_date = (
        insurance_fact.get("ELIGIBILITY_CHECK_DATE")
        if insurance_fact else None
    )
    is_fresh = _is_freshly_verified(
        eligibility_check_date,
        ELIGIBILITY_FRESHNESS_DAYS,
    )
    place_of_service = "hospital" if case.get("facility_id") else "clinic"

    print(f"   demographics_complete: {demographics_complete}")
    print(f"   has_insurance        : {has_insurance}")
    print(f"   eligibility_fresh    : {is_fresh}")
    print(f"   place_of_service     : {place_of_service}")

    facts_considered.update({
        "is_self_pay": False,
        "demographics_complete": demographics_complete,
        "has_insurance": has_insurance,
        "eligibility_check_date": eligibility_check_date,
        "is_freshly_verified": is_fresh,
        "eligibility_freshness_days": ELIGIBILITY_FRESHNESS_DAYS,
        "place_of_service": place_of_service,
    })

    if not demographics_complete or not has_insurance:
        if place_of_service == "clinic":
            next_state = "HUMAN_QUEUE"
            outcome_code = "REGISTRATION_INCOMPLETE_CLINIC"
        else:
            next_state = STATE_START_REGISTRATION_QUEUE
            outcome_code = "REGISTRATION_INCOMPLETE_HOSPITAL"

        print(f"   DECISION → {next_state}")

        log.info(
            "node3.verify_demo_ins.DECISION",
            case_id=case_id,
            routing_decision=outcome_code,
            next_state=next_state,
            duration_ms=_ms(node3_start),
        )

        _write_node_history(
            client=tools_client,
            case_id=case_id,
            task_id=task_id,
            run_id=run_id,
            node_key=node3_key,
            node_index=3,
            duration_ms=_ms(node3_start),
            outcome_code=outcome_code,
            output_summary={
                "next_state": next_state,
                "demographics_complete": demographics_complete,
                "has_insurance": has_insurance,
            },
        )

        return _build_result(
            case_id=case_id,
            task_id=task_id,
            next_state=next_state,
            outcome_code=outcome_code,
            note=f"Demographics or insurance missing. POS={place_of_service}",
            facts_considered=facts_considered,
            tools_invoked=tools_invoked,
            confidence_score=0.9,
            duration_ms=_ms(flow_start),
        )

    if is_fresh:
        print(f"   DECISION → {STATE_CASE_READY_FOR_CLAIM_CREATION}")

        log.info(
            "node3.verify_demo_ins.DECISION",
            case_id=case_id,
            routing_decision="CLAIM_READY",
            next_state=STATE_CASE_READY_FOR_CLAIM_CREATION,
            duration_ms=_ms(node3_start),
        )

        _write_node_history(
            client=tools_client,
            case_id=case_id,
            task_id=task_id,
            run_id=run_id,
            node_key=node3_key,
            node_index=3,
            duration_ms=_ms(node3_start),
            outcome_code="READY_FOR_CLAIM_CREATION",
            output_summary={"next_state": STATE_CASE_READY_FOR_CLAIM_CREATION},
        )

        return _build_result(
            case_id=case_id,
            task_id=task_id,
            next_state=STATE_CASE_READY_FOR_CLAIM_CREATION,
            outcome_code="READY_FOR_CLAIM_CREATION",
            note="Demographics complete and eligibility recently verified",
            facts_considered=facts_considered,
            tools_invoked=tools_invoked,
            confidence_score=1.0,
            duration_ms=_ms(flow_start),
        )

    print(f"   DECISION → {STATE_ELIGIBILITY_VERIFICATION_QUEUE}")

    log.info(
        "node3.verify_demo_ins.DECISION",
        case_id=case_id,
        routing_decision="ELIGIBILITY_STALE",
        next_state=STATE_ELIGIBILITY_VERIFICATION_QUEUE,
        eligibility_check_date=eligibility_check_date,
        duration_ms=_ms(node3_start),
    )

    _write_node_history(
        client=tools_client,
        case_id=case_id,
        task_id=task_id,
        run_id=run_id,
        node_key=node3_key,
        node_index=3,
        duration_ms=_ms(node3_start),
        outcome_code="ELIGIBILITY_STALE",
        output_summary={"next_state": STATE_ELIGIBILITY_VERIFICATION_QUEUE},
    )

    return _build_result(
        case_id=case_id,
        task_id=task_id,
        next_state=STATE_ELIGIBILITY_VERIFICATION_QUEUE,
        outcome_code="ELIGIBILITY_STALE",
        note="Insurance present but eligibility not recently verified",
        facts_considered=facts_considered,
        tools_invoked=tools_invoked,
        confidence_score=0.95,
        duration_ms=_ms(flow_start),
    )


def _get_fact(facts: list[dict], key: str) -> dict | None:
    for f in facts:
        if f.get("FACT_KEY") == key:
            parsed = f.get("FACT_VALUE_PARSED")
            return parsed if parsed else {}
    return None


def _is_self_pay(patient_fact: dict | None) -> bool:
    if not patient_fact:
        return False
    billing = patient_fact.get("BILLING_METHOD")
    is_sp = patient_fact.get("IS_SELF_PAY")
    return billing == 0 or billing == "0" or bool(is_sp)


def _is_demographics_complete(demographics_fact: dict | None) -> bool:
    if not demographics_fact:
        return False
    return all(bool(demographics_fact.get(field)) for field in REQUIRED_DEMO_FIELDS)


def _is_freshly_verified(check_date_str: str | None, freshness_days: int) -> bool:
    if not check_date_str:
        return False
    try:
        check_date = datetime.strptime(check_date_str[:10], "%Y-%m-%d").date()
        cutoff = date.today() - timedelta(days=freshness_days)
        return check_date >= cutoff
    except (ValueError, TypeError):
        return False


def _ms(start: float) -> int:
    return round((time.time() - start) * 1000)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_result(
    case_id: int,
    task_id: int | None,
    next_state: str,
    outcome_code: str,
    note: str,
    facts_considered: dict,
    tools_invoked: list[str],
    confidence_score: float,
    duration_ms: int,
) -> dict:
    result = {
        "case_id": case_id,
        "task_id": task_id,
        "handler_key": HANDLER_INITIALIZE,
        "next_state": next_state,
        "outcome_code": outcome_code,
        "note": note,
        "facts_considered": facts_considered,
        "tools_invoked": tools_invoked,
        "confidence_score": confidence_score,
        "duration_ms": duration_ms,
        "completed_at": _now_iso(),
    }
    print(f"\n   RESULT → next_state: {next_state} | outcome: {outcome_code}")
    return result


def _write_node_history(
    client: object,
    case_id: int,
    task_id: int | None,
    run_id: str,
    node_key: str,
    node_index: int,
    duration_ms: int,
    outcome_code: str,
    output_summary: dict,
) -> None:
    try:
        client.create_step_history({
            "case_id": case_id,
            "correlation_id": run_id,
            "handler_key": node_key,
            "outcome_code": outcome_code,
            "output_summary_json": output_summary,
            "started_at": _now_iso(),
            "ended_at": _now_iso(),
        })
    except Exception as exc:
        log.warning(
            "initialize.node_history_failed",
            node_key=node_key,
            error=str(exc),
        )