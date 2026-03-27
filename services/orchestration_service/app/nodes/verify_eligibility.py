"""
Node: Verify Eligibility

Runs when the case is in ELIGIBILITY_VERIFICATION_QUEUE.
Orchestrates:
  1. Load insurance + payer linkage
  2. OCR → LLM extraction on any attached document
  3. Medicare Advantage conflict resolution
  4. Duplicate policy deactivation
  5. Electronic eligibility via Availity
  6. Manual fallback for WC/auto/PI and unsupported payers
"""
from __future__ import annotations

from shared.constants import (
    FACT_SCOPE_ELIGIBILITY,
    HANDLER_VERIFY_ELIGIBILITY,
    MANUAL_ELIGIBILITY_INSURANCE_TYPES,
    STATE_CASE_READY_FOR_CLAIM_CREATION,
    STATE_FIX_ELIGIBILITY_ERROR_QUEUE,
    STATE_MANUAL_ELIGIBILITY_VERIFICATION_QUEUE,
    TASK_OPEN,
)
from shared.logging import get_logger
from .common import build_result, get_primary_insurance, iso_offset

import time

log = get_logger(__name__)


def run_verify_eligibility(state: dict, tools_client) -> dict:
    case = state["case"]
    case_id = case["case_id"]
    patient_id = case["patient_id"]
    tools_invoked: list[str] = []
    facts_considered: dict = {}
    node_start = time.time()

    log.info("node.elg.start", case_id=case_id, patient_id=patient_id, node="verify_eligibility")

    # ── 1. Load insurances ────────────────────────────────────────────────────
    insurances = tools_client.get_patient_insurances(patient_id)
    tools_invoked.append("get_patient_insurances")

    if not insurances:
        node_ms = round((time.time() - node_start) * 1000)
        log.warning("node.elg.no_insurance", case_id=case_id, node="verify_eligibility", duration_ms=node_ms)
        return build_result(
            state,
            HANDLER_VERIFY_ELIGIBILITY,
            next_state=STATE_FIX_ELIGIBILITY_ERROR_QUEUE,
            outcome_code="NO_ACTIVE_INSURANCE",
            note="No active insurance found; routed to fix queue",
            tools_invoked=tools_invoked,
            node_count=1,
        )

    facts_considered["insurance_count"] = len(insurances)

    # ── 2. Medicare / Medicare Advantage conflict ──────────────────────────────
    ma_resolution = _resolve_medicare_advantage(insurances)
    if ma_resolution.get("conflict_detected"):
        # Deactivate the plain Medicare record; verify MA plan instead
        if ma_resolution.get("deactivate_id"):
            tools_client.deactivate_insurance(ma_resolution["deactivate_id"])
            tools_invoked.append(f"deactivate_insurance:{ma_resolution['deactivate_id']}")
            # Refresh
            insurances = tools_client.get_patient_insurances(patient_id)
            tools_invoked.append("get_patient_insurances")

    # ── 3. Duplicate policy detection (same tier, same policy_no, missing group) ─
    insurances = _deactivate_duplicate_policies(insurances, tools_client, tools_invoked)

    # ── 4. Separate primary and secondary ─────────────────────────────────────
    primary = get_primary_insurance(insurances)
    secondary = next((i for i in insurances if i.get("ranking") == 2), None)

    if not primary:
        node_ms = round((time.time() - node_start) * 1000)
        log.warning("node.elg.no_primary", case_id=case_id, node="verify_eligibility", duration_ms=node_ms)
        return build_result(
            state,
            HANDLER_VERIFY_ELIGIBILITY,
            next_state=STATE_FIX_ELIGIBILITY_ERROR_QUEUE,
            outcome_code="NO_PRIMARY_INSURANCE",
            note="Could not identify primary insurance after deduplication",
            tools_invoked=tools_invoked,
            node_count=1,
        )

    facts_considered["primary_insurance_id"] = primary.get("insurance_id")
    facts_considered["availity_payer_no"] = primary.get("availity_payer_no")

    # ── 5. Check OCR/LLM result for document-backed extraction ────────────────
    case_docs = tools_client.list_case_documents(case_id)
    tools_invoked.append("list_case_documents")
    pending_docs = [d for d in case_docs if d.get("status_code") in ("RECEIVED", "OCR_COMPLETE")]

    if pending_docs:
        doc = pending_docs[0]
        doc_id = doc["document_id"]

        if doc["status_code"] == "RECEIVED":
            ocr = tools_client.ocr_extract(doc_id, mode="insurance_card")
            tools_invoked.append(f"ocr_extract:{doc_id}")
        else:
            ocr = {}

        if ocr.get("ocr_text"):
            llm = tools_client.llm_parse_insurance(doc_id)
            tools_invoked.append(f"llm_parse_insurance:{doc_id}")
            facts_considered["llm_confidence"] = llm.get("confidence", 0)
            facts_considered["llm_member_id"] = llm.get("member_id")

    # ── 6. Manual eligibility check ───────────────────────────────────────────
    ins_type = primary.get("insurance_type")
    availity_payer_no = primary.get("availity_payer_no") or ""
    elg_enrollment = primary.get("elg_enrollment", 0)

    # Manual route: WC/auto/PI, or no Availity payer number, or not enrolled
    if _requires_manual(ins_type, availity_payer_no, elg_enrollment):
        log.info(
            "node.elg.DECISION",
            case_id=case_id,
            routing_decision="MANUAL_REQUIRED",
            next_state=STATE_MANUAL_ELIGIBILITY_VERIFICATION_QUEUE,
            node="verify_eligibility",
        )
        tools_client.create_task({
            "case_id": case_id,
            "task_type": "MANUAL_ELIGIBILITY",
            "intent_key": f"MANUAL_ELG:{case_id}",
            "state_code": TASK_OPEN,
            "queue_id": STATE_MANUAL_ELIGIBILITY_VERIFICATION_QUEUE,
            "handler_key": "DEMO_MANUAL_ELIGIBILITY",
            "priority_rank": 60,
            "payload_json": {
                "insurance_id": primary.get("insurance_id"),
                "insurance_type": ins_type,
                "payer_name": primary.get("payer_name"),
                "reason": _manual_reason(ins_type, availity_payer_no, elg_enrollment),
            },
        })
        tools_invoked.append("create_task:MANUAL_ELIGIBILITY")
        
        node_ms = round((time.time() - node_start) * 1000)
        return build_result(
            state,
            HANDLER_VERIFY_ELIGIBILITY,
            next_state=STATE_MANUAL_ELIGIBILITY_VERIFICATION_QUEUE,
            outcome_code="MANUAL_ELIGIBILITY_REQUIRED",
            note=_manual_reason(ins_type, availity_payer_no, elg_enrollment),
            facts_considered=facts_considered,
            tools_invoked=tools_invoked,
            confidence_score=0.8,
            node_count=1,
        )

    # ── 7. Electronic eligibility via Availity ────────────────────────────────
    patient = tools_client.get_patient(patient_id)
    tools_invoked.append("get_patient")

    verify_payload = {
        "case_id": case_id,
        "patient_id": patient_id,
        "insurance_id": primary.get("insurance_id"),
        "clearinghouse": "AVAILITY",
        "payer_info_id": primary.get("payer_info_id"),
        "payer_number": availity_payer_no,
        "request_payload": {
            "member_id": primary.get("policy_no"),
            "group_no": primary.get("group_no"),
            "subscriber_first_name": primary.get("policy_holder_f_name"),
            "subscriber_last_name": primary.get("policy_holder_l_name"),
            "provider_npi": case.get("context_json", {}).get("provider_npi", ""),
            "service_type_code": "30",
        },
    }

    elg_result = tools_client.verify_eligibility(verify_payload)
    tools_invoked.append("verify_eligibility")
    facts_considered["coverage_status"] = elg_result.get("coverage_status")
    facts_considered["result_code"] = elg_result.get("result_code")

    if elg_result.get("coverage_status") == "ACTIVE" or elg_result.get("result_code") == "ACTIVE":
        # Attempt secondary if present
        if secondary:
            _verify_secondary(state, secondary, patient, tools_client, tools_invoked)

        node_ms = round((time.time() - node_start) * 1000)
        log.info(
            "node.elg.DECISION",
            case_id=case_id,
            routing_decision="ACTIVE",
            next_state=STATE_CASE_READY_FOR_CLAIM_CREATION,
            duration_ms=node_ms,
            node="verify_eligibility"
        )
        return build_result(
            state,
            HANDLER_VERIFY_ELIGIBILITY,
            next_state=STATE_CASE_READY_FOR_CLAIM_CREATION,
            outcome_code="ELIGIBILITY_VERIFIED_ACTIVE",
            note="Primary eligibility verified as ACTIVE",
            facts_considered=facts_considered,
            tools_invoked=tools_invoked,
            confidence_score=0.98,
            node_count=1,
        )

    # Inactive / error result
    node_ms = round((time.time() - node_start) * 1000)
    log.info(
        "node.elg.DECISION",
        case_id=case_id,
        routing_decision="INACTIVE_OR_ERROR",
        next_state=STATE_FIX_ELIGIBILITY_ERROR_QUEUE,
        duration_ms=node_ms,
        node="verify_eligibility"
    )
    return build_result(
        state,
        HANDLER_VERIFY_ELIGIBILITY,
        next_state=STATE_FIX_ELIGIBILITY_ERROR_QUEUE,
        outcome_code="ELIGIBILITY_NOT_ACTIVE",
        note=f"Eligibility returned {elg_result.get('result_code')}: {elg_result.get('result_note')}",
        facts_considered=facts_considered,
        tools_invoked=tools_invoked,
        confidence_score=0.9,
        node_count=1,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _requires_manual(ins_type: int | None, payer_no: str, elg_enrollment: int) -> bool:
    """Return True when this policy cannot be verified electronically."""
    if ins_type == 9:  # Other = WC / auto / PI
        return True
    if not payer_no:
        return True
    if elg_enrollment == 0:
        return True
    return False


def _manual_reason(ins_type: int | None, payer_no: str, elg_enrollment: int) -> str:
    if ins_type == 9:
        return "Insurance type requires manual verification (WC/auto/PI or unmapped)"
    if not payer_no:
        return "Availity payer number not configured for this payer"
    if elg_enrollment == 0:
        return "Payer not enrolled for electronic eligibility at this clearinghouse"
    return "Manual verification required"


def _resolve_medicare_advantage(insurances: list[dict]) -> dict:
    """
    Detect coexisting Medicare and Medicare Advantage policies.
    Returns { conflict_detected: bool, deactivate_id: int|None }.
    """
    medicare_ids = []
    advantage_ids = []
    for ins in insurances:
        name = (ins.get("payer_name") or "").lower()
        if "advantage" in name or "ma " in name:
            advantage_ids.append(ins["insurance_id"])
        elif "medicare" in name:
            medicare_ids.append(ins["insurance_id"])

    if medicare_ids and advantage_ids:
        return {"conflict_detected": True, "deactivate_id": medicare_ids[0]}
    return {"conflict_detected": False, "deactivate_id": None}


def _deactivate_duplicate_policies(
    insurances: list[dict],
    tools_client,
    tools_invoked: list[str],
) -> list[dict]:
    """
    Within each ranking tier, if two policies share the same policy_no,
    deactivate the one that lacks a group_no.
    Returns the filtered list.
    """
    seen: dict[tuple, int] = {}  # (ranking, policy_no) → insurance_id with group_no
    to_deactivate: list[int] = []

    for ins in insurances:
        key = (ins.get("ranking"), (ins.get("policy_no") or "").upper())
        if key in seen:
            # Keep the one with group_no; deactivate the other
            if not ins.get("group_no"):
                to_deactivate.append(ins["insurance_id"])
            else:
                to_deactivate.append(seen[key])
                seen[key] = ins["insurance_id"]
        else:
            seen[key] = ins["insurance_id"]

    for iid in to_deactivate:
        try:
            tools_client.deactivate_insurance(iid)
            tools_invoked.append(f"deactivate_insurance:{iid}")
        except Exception as exc:
            log.warning("verify_eligibility.deactivate_failed", insurance_id=iid, error=str(exc))

    return [i for i in insurances if i["insurance_id"] not in to_deactivate]


def _verify_secondary(
    state: dict,
    secondary: dict,
    patient: dict,
    tools_client,
    tools_invoked: list[str],
) -> None:
    """Best-effort secondary eligibility — failures are non-blocking."""
    payer_no = secondary.get("availity_payer_no")
    if not payer_no:
        return
    try:
        payload = {
            "case_id": state["case"]["case_id"],
            "patient_id": state["case"]["patient_id"],
            "insurance_id": secondary.get("insurance_id"),
            "clearinghouse": "AVAILITY",
            "payer_number": payer_no,
            "request_payload": {
                "member_id": secondary.get("policy_no"),
                "group_no": secondary.get("group_no"),
            },
        }
        tools_client.verify_eligibility(payload)
        tools_invoked.append(f"verify_eligibility_secondary:{secondary.get('insurance_id')}")
    except Exception as exc:
        log.warning(
            "verify_eligibility.secondary_failed",
            case_id=state["case"]["case_id"],
            error=str(exc),
        )
