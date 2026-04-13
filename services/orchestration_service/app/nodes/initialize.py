from __future__ import annotations

import time
import uuid
from datetime import date, datetime, timedelta, timezone

from shared.logging import get_logger
from shared.constants import HANDLER_INITIALIZE

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

    patient_fact = _get_fact(facts, "PATIENT_INFO")
    insurance_fact = _get_fact(facts, "INSURANCE_INFO")
    orchestration_fact = _get_fact(facts, "ORCHESTRATION_INFO")

    print(f"   PATIENT_INFO      : {'found' if patient_fact else '❌ missing'}")
    print(f"   INSURANCE_INFO    : {'found' if insurance_fact else '❌ missing'}")
    print(f"   ORCHESTRATION_INFO: {'found' if orchestration_fact else '❌ missing'}")

    log.info(
        "node1.fetch_facts.complete",
        case_id=case_id,
        total_facts=len(facts),
        has_patient_info=patient_fact is not None,
        has_insurance_info=insurance_fact is not None,
        has_orchestration_info=orchestration_fact is not None,
        duration_ms=_ms(node1_start),
        run_id=run_id,
    )

    facts_considered.update({
        "task_id": task_id,
        "case_id": case_id,
        "clinic_id": case.get("clinic_id"),
        "patient_id": case.get("patient_id"),
        "has_patient_info": patient_fact is not None,
        "has_insurance_info": insurance_fact is not None,
        "has_orchestration_info": orchestration_fact is not None,
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
            "has_patient_info": patient_fact is not None,
            "has_insurance_info": insurance_fact is not None,
            "has_orchestration_info": orchestration_fact is not None,
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

    # ── Source of truth is the Data Loader fact ────────────
    has_duplicates = orchestration_fact.get("DUPLICATE_FLAG", False) if orchestration_fact else False
    duplicate_patients = []

    # If the fact says there are duplicates, we attempt to fetch them from the API for context
    if has_duplicates:
        dup_payload = {
            "first_name" : patient_fact.get("FIRST_NAME") if patient_fact else None,
            "last_name"  : patient_fact.get("LAST_NAME")  if patient_fact else None,
            "dob"        : patient_fact.get("DOB") if patient_fact else None,
            "patient_id" : case.get("patient_id"),
        }
        try:
            dup_result = tools_client.duplicate_check(
                dup_payload,
                clinic_id=case.get("clinic_id", 0),
                patient_id=case.get("patient_id", 0),
            )
            tools_invoked.append("duplicate_check")
            # Grab candidates if any exist, but DO NOT override the has_duplicates flag
            duplicate_patients = dup_result.get("candidates", [])
        except Exception as exc:
            print(f"   Node 2: API fetch failed, but DUPLICATE_FLAG is True → {exc}")

    print(f"   duplicate_check_flag → {has_duplicates} (Loaded {len(duplicate_patients)} candidates for context)")

    if has_duplicates:
        duplicate_ids = [str(d.get("patient_id", "")) for d in duplicate_patients] if duplicate_patients else ["MOCK_DUP_ID_001"]

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
            outcome_code="DUPLICATE_PATIENT",
            output_summary={
                "next_state": "VERIFY_DUPLICATE_PATIENT",
                "duplicate_ids": duplicate_ids,
            },
        )

        return _build_result(
            case_id=case_id,
            task_id=task_id,
            next_state="VERIFY_DUPLICATE_PATIENT",
            outcome_code="DUPLICATE_PATIENT",
            note=f"Duplicate found: {len(duplicate_patients)} candidate(s).",
            facts_considered=facts_considered,
            tools_invoked=tools_invoked,
            confidence_score=1.0,
            duration_ms=_ms(flow_start),
        )

    print("No duplicate found")

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

    is_self_pay = orchestration_fact.get("SELF_PAY_FLAG", False) if orchestration_fact else False
    demographics_complete = orchestration_fact.get("DEMOGRAPHICS_COMPLETE", False) if orchestration_fact else False
    has_insurance = orchestration_fact.get("HAS_INSURANCE", False) if orchestration_fact else False
    eligibility_check_date = orchestration_fact.get("LAST_ELIGIBILITY_CHECK_DATE") if orchestration_fact else None
    
    is_verified_within_30_days = _is_freshly_verified(
        eligibility_check_date,
        ELIGIBILITY_FRESHNESS_DAYS, # 30 Days
    )
    place_of_service = orchestration_fact.get("PLACE_OF_SERVICE", "clinic") if orchestration_fact else "clinic"

    print(f"   is_self_pay          : {is_self_pay}")
    print(f"   demographics_complete: {demographics_complete}")
    print(f"   has_insurance        : {has_insurance}")
    print(f"   verified_within_30_ds: {is_verified_within_30_days}")
    print(f"   place_of_service     : {place_of_service}")

    facts_considered.update({
        "is_self_pay": is_self_pay,
        "demographics_complete": demographics_complete,
        "has_insurance": has_insurance,
        "eligibility_check_date": eligibility_check_date,
        "is_verified_within_30_days": is_verified_within_30_days,
        "eligibility_freshness_days": ELIGIBILITY_FRESHNESS_DAYS,
        "place_of_service": place_of_service,
    })

    # ── Canonical Truth Table (matches truth table exactly) ──────────────────
    # Diamond 1: do we have all demographics + insurance from client EMR?
    if demographics_complete and has_insurance:
        # Diamond 2: insurance verified within the past 30 days?
        if is_verified_within_30_days:
            # HAS_DEMO=YES + HAS_INS=YES + INS_VERIFIED_<30D=YES
            outcome_code = "CLAIM_CREATION"
            next_state   = "CLAIM_CREATION_QUEUE"
            note         = "Demographics complete and eligibility recently verified"
        else:
            # HAS_DEMO=YES + HAS_INS=YES + INS_VERIFIED_<30D=NO
            outcome_code = "VERIFY_ELIGIBILITY"
            next_state   = "VERIFY_ELIGIBILITY"
            note         = "Insurance present but eligibility not recently verified"
    else:
        # HAS_DEMO=NO or HAS_INS=NO
        if is_self_pay:
            # IS_SELF_PAY=YES
            outcome_code = "SELF_PAY_PATIENT"
            next_state   = "CLOSE"
            note         = "Patient is self-pay"
        else:
            # IS_SELF_PAY=NO → check place of service
            if place_of_service == "hospital":
                # IS_HOSPITAL=YES
                outcome_code = "NO_DEMO_HOSPITAL_PATIENT"
                next_state   = "ACQUIRE_FACESHEET"
                note         = "Hospital POS - routing to patient registration"
            else:
                # IS_CLINIC=YES
                outcome_code = "NO_DEMO_CLINIC_PATIENT"
                next_state   = "ACQUIRE_FACESHEET"
                note         = "Clinic POS - check insurance in clinic EMR system"

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
        },
    )

    return _build_result(
        case_id=case_id,
        task_id=task_id,
        next_state=next_state,
        outcome_code=outcome_code,
        note=note,
        facts_considered=facts_considered,
        tools_invoked=tools_invoked,
        confidence_score=0.95 if is_self_pay else 0.90,
        duration_ms=_ms(flow_start),
    )


def _get_fact(facts: list[dict], key: str) -> dict | None:
    for f in facts:
        if f.get("FACT_KEY") == key:
            parsed = f.get("FACT_VALUE_PARSED")
            return parsed if parsed else {}
    return None





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
            "task_id": task_id,
            "correlation_id": run_id,
            "handler_key": node_key,
            "node_index": node_index,
            "duration_ms": duration_ms,
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