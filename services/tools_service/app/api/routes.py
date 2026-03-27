"""
Tools Service API — all endpoints called by Temporal activities and LangGraph nodes.

All writes to allofactorv3 and rcm_workflow go through this layer.
No orchestration or workflow code writes to the DB directly.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.orm import Session

from shared.config import get_settings
from shared.constants import (
    TASK_OPEN, TASK_DONE, TASK_CANCELED,
    FACT_SCOPE_DEMOGRAPHICS, FACT_SCOPE_ELIGIBILITY,
)
from shared.logging import get_logger
from ..core.deps import get_workflow_db, get_claims_db
from ..repositories.workflow_repo import WorkflowRepository
from ..repositories.claims_repo import ClaimsRepository
from ..schemas.case import CaseCreate, CaseEvent, CaseResponse, CaseUpdate
from ..schemas.document import DocumentCreate, DocumentOCRRequest
from ..schemas.eligibility import EligibilityResultCreate, EligibilityVerifyRequest
from ..schemas.fact import FactCreate, FactsBulkCreate
from ..schemas.step_history import StepHistoryCreate
from ..schemas.task import TaskCreate, TaskUpdate
from ..services.eligibility_service import EligibilityService
from ..services.llm_service import LLMService
from ..services.ocr_service import OCRService
from ..services.profile_engine_service import ProfileEngineService
from ..services.s3_service import S3Service

router = APIRouter()
log = get_logger(__name__)
settings = get_settings()


# ── Auth guard ────────────────────────────────────────────────────────────────

def _verify_internal(x_api_secret: str | None = Header(default=None)) -> None:
    """Simple shared-secret guard for internal service-to-service calls."""
    if settings.app_env != "local" and x_api_secret != settings.internal_api_secret:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ═══════════════════════════════════════════════════════════════════════════════
# RCM Cases
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/rcm/cases", response_model=CaseResponse, status_code=201)
def create_case(
    payload: CaseCreate,
    db: Session = Depends(get_workflow_db),
    _: None = Depends(_verify_internal),
):
    """Idempotent case creation — returns existing case if charge_id already has one."""
    row = WorkflowRepository(db).create_case(payload)
    return _case_to_response(row)


@router.get("/rcm/cases/{case_id}", response_model=CaseResponse)
def get_case(
    case_id: int,
    db: Session = Depends(get_workflow_db),
):
    row = WorkflowRepository(db).get_case(case_id)
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return _case_to_response(row)


@router.get("/rcm/cases/{case_id}/full")
def get_case_full(
    case_id: int,
    db: Session = Depends(get_workflow_db),
):
    """Returns case + open tasks + facts as a single payload for the orchestration layer."""
    data = WorkflowRepository(db).get_case_full(case_id)
    if not data:
        raise HTTPException(status_code=404, detail="Case not found")
    return data


@router.patch("/rcm/cases/{case_id}", response_model=CaseResponse)
def update_case(
    case_id: int,
    payload: CaseUpdate,
    db: Session = Depends(get_workflow_db),
    _: None = Depends(_verify_internal),
):
    try:
        row = WorkflowRepository(db).update_case(case_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _case_to_response(row)


@router.post("/rcm/cases/{case_id}/events")
def case_event(
    case_id: int,
    payload: CaseEvent,
    db: Session = Depends(get_workflow_db),
    _: None = Depends(_verify_internal),
):
    """
    Signal a case event (DOCUMENT_UPLOADED, TASK_COMPLETED, etc.).
    Persists the event as a step_history entry and returns accepted.
    The Temporal signal should be sent by the caller after this returns.
    """
    repo = WorkflowRepository(db)
    case = repo.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    repo.create_step_history(
        StepHistoryCreate(
            case_id=case_id,
            correlation_id=payload.correlation_id,
            trigger_type="EVENT",
            handler_key=f"EVENT:{payload.event_type}",
            state_before=case.state_code,
            state_after=case.state_code,
            outcome_code="EVENT_RECEIVED",
            output_summary_json={"event_type": payload.event_type, "payload": payload.payload},
        )
    )
    return {"case_id": case_id, "accepted": True, "event_type": payload.event_type}


@router.get("/rcm/cases/due/list")
def list_cases_due(
    limit: int = Query(200, le=500),
    db: Session = Depends(get_workflow_db),
    _: None = Depends(_verify_internal),
):
    """Returns cases whose next_action_at has passed (for the Temporal-adjacent scheduler)."""
    cases = WorkflowRepository(db).list_cases_due(limit=limit)
    return [{"case_id": c.case_id, "state_code": c.state_code, "next_action_at": c.next_action_at} for c in cases]


# ═══════════════════════════════════════════════════════════════════════════════
# RCM Tasks
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/rcm/tasks/{task_id}")
def get_task(
    task_id: int,
    db: Session = Depends(get_workflow_db),
    _: None = Depends(_verify_internal),
):
    task = WorkflowRepository(db).get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_dict(task)


@router.post("/rcm/tasks", status_code=201)
def upsert_task(
    payload: TaskCreate,
    db: Session = Depends(get_workflow_db),
    _: None = Depends(_verify_internal),
):
    task = WorkflowRepository(db).upsert_task(payload)
    return _task_dict(task)


@router.patch("/rcm/tasks/{task_id}")
def update_task(
    task_id: int,
    payload: TaskUpdate,
    db: Session = Depends(get_workflow_db),
    _: None = Depends(_verify_internal),
):
    try:
        task = WorkflowRepository(db).update_task(task_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _task_dict(task)


@router.get("/rcm/cases/{case_id}/tasks")
def list_tasks(
    case_id: int,
    state: str | None = Query(None),
    db: Session = Depends(get_workflow_db),
):
    repo = WorkflowRepository(db)
    if state:
        from sqlalchemy import select
        from ..models.workflow import RcmTask
        tasks = list(db.scalars(
            select(RcmTask).where(
                RcmTask.case_id == case_id,
                RcmTask.state_code == state.upper(),
            )
        ))
    else:
        tasks = repo.list_open_tasks(case_id)
    return [_task_dict(t) for t in tasks]


@router.post("/rcm/cases/{case_id}/tasks/cancel-all")
def cancel_open_tasks(
    case_id: int,
    reason: str = Query("SUPERSEDED"),
    db: Session = Depends(get_workflow_db),
    _: None = Depends(_verify_internal),
):
    count = WorkflowRepository(db).cancel_open_tasks_for_case(case_id, reason)
    return {"case_id": case_id, "canceled": count}


# ═══════════════════════════════════════════════════════════════════════════════
# RCM Facts
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/rcm/facts", status_code=201)
def create_fact(
    payload: FactCreate,
    db: Session = Depends(get_workflow_db),
    _: None = Depends(_verify_internal),
):
    fact = WorkflowRepository(db).create_fact(payload)
    return {"fact_id": fact.fact_id}


@router.post("/rcm/facts/bulk", status_code=201)
def create_facts_bulk(
    payload: FactsBulkCreate,
    db: Session = Depends(get_workflow_db),
    _: None = Depends(_verify_internal),
):
    facts = WorkflowRepository(db).bulk_create_facts(payload.facts)
    return {"created": len(facts), "fact_ids": [f.fact_id for f in facts]}


@router.get("/rcm/cases/{case_id}/facts")
def list_facts(
    case_id: int,
    db: Session = Depends(get_workflow_db),
):
    rows = WorkflowRepository(db).list_facts(case_id)
    return [
        {
            "fact_id": r.fact_id,
            "fact_scope": r.fact_scope,
            "fact_key": r.fact_key,
            "fact_value_str": r.fact_value_str,
            "fact_value_num": r.fact_value_num,
            "source_system": r.source_system,
            "confidence_score": r.confidence_score,
        }
        for r in rows
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# Step History
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/rcm/step-history", status_code=201)
def create_step_history(
    payload: StepHistoryCreate,
    db: Session = Depends(get_workflow_db),
    _: None = Depends(_verify_internal),
):
    row = WorkflowRepository(db).create_step_history(payload)
    return {"step_history_id": row.step_history_id}


@router.get("/rcm/cases/{case_id}/step-history")
def get_step_history(
    case_id: int,
    db: Session = Depends(get_workflow_db),
):
    rows = WorkflowRepository(db).list_step_history(case_id)
    return [
        {
            "step_history_id": r.step_history_id,
            "handler_key": r.handler_key,
            "state_before": r.state_before,
            "state_after": r.state_after,
            "outcome_code": r.outcome_code,
            "started_at": r.started_at,
            "ended_at": r.ended_at,
            "confidence_score": r.confidence_score,
        }
        for r in rows
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# Documents
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/documents", status_code=201)
def create_document(
    payload: DocumentCreate,
    db: Session = Depends(get_workflow_db),
    _: None = Depends(_verify_internal),
):
    """
    Register a document that has already been uploaded to S3.
    Validates S3 object existence before writing the DB row.
    """
    s3 = S3Service()
    try:
        s3.head_object(payload.s3_bucket, payload.s3_key)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"S3 object not accessible: {exc}")
    row = WorkflowRepository(db).create_document(payload)
    return {"document_id": row.document_id, "s3_key": row.s3_key, "status_code": row.status_code}


@router.get("/documents/{document_id}")
def get_document(
    document_id: int,
    db: Session = Depends(get_workflow_db),
):
    doc = WorkflowRepository(db).get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "document_id": doc.document_id,
        "document_type": doc.document_type,
        "source_type": doc.source_type,
        "s3_bucket": doc.s3_bucket,
        "s3_key": doc.s3_key,
        "status_code": doc.status_code,
        "patient_id": doc.patient_id,
        "case_id": doc.case_id,
    }


@router.get("/documents/{document_id}/presigned-url")
def get_document_presigned_url(
    document_id: int,
    expires_in: int = Query(3600, le=86400),
    db: Session = Depends(get_workflow_db),
):
    doc = WorkflowRepository(db).get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    url = S3Service().presigned_url(doc.s3_bucket, doc.s3_key, expires_in=expires_in)
    return {"document_id": document_id, "url": url, "expires_in": expires_in}


@router.get("/documents/upload-url/new")
def get_upload_presigned_url(
    clinic_id: int,
    patient_id: int,
    document_type: str,
    filename: str,
    content_type: str = Query("application/pdf"),
    _: None = Depends(_verify_internal),
):
    """Return a pre-signed S3 URL so clients can upload documents directly."""
    s3 = S3Service()
    key = s3.build_key(
        clinic_id=clinic_id,
        patient_id=patient_id,
        document_type=document_type,
        document_id=str(uuid.uuid4()),
        filename=filename,
    )
    post = s3.presigned_upload_url(s3.default_bucket, key, content_type=content_type)
    return {"bucket": s3.default_bucket, "key": key, "presigned_post": post}


@router.get("/rcm/cases/{case_id}/documents")
def list_case_documents(
    case_id: int,
    db: Session = Depends(get_workflow_db),
):
    docs = WorkflowRepository(db).list_documents_for_case(case_id)
    return [
        {
            "document_id": d.document_id,
            "document_type": d.document_type,
            "status_code": d.status_code,
            "s3_key": d.s3_key,
            "uploaded_at": d.uploaded_at,
        }
        for d in docs
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# Patients (read from allofactorv3)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/patients/{patient_id}")
def get_patient(
    patient_id: int,
    db: Session = Depends(get_claims_db),
):
    patient = ClaimsRepository(db).get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return _patient_dict(patient)


@router.get("/patients/{patient_id}/insurances")
def get_patient_insurances(
    patient_id: int,
    active_only: bool = Query(True),
    db: Session = Depends(get_claims_db),
):
    repo = ClaimsRepository(db)
    insurances = repo.get_patient_insurances(patient_id, active_only=active_only)
    result = []
    for ins in insurances:
        business, payer_info = repo.get_payer_info_for_insurance(ins)
        result.append({
            "insurance_id": ins.INSURANCE_ID,
            "company_id": ins.COMPANY_ID,
            "policy_no": ins.POLICY_NO,
            "group_no": ins.GROUP_NO,
            "insurance_type": ins.INSURANCE_TYPE,
            "ranking": ins.RANKING,
            "active": ins.ACTIVE,
            "eligibility_status": ins.ELIGIBILITY_STATUS,
            "eligibility_check_date": str(ins.ELIGIBILITY_CHECK_DATE) if ins.ELIGIBILITY_CHECK_DATE else None,
            "copay": ins.COPAY,
            "coins": ins.COINS,
            "deductable": ins.DEDUCTABLE,
            "payer_name": ins.PAYER_NAME,
            "policy_holder_f_name": ins.POLICY_HOLDER_F_NAME,
            "policy_holder_l_name": ins.POLICY_HOLDER_L_NAME,
            "business_name": getattr(business, "NAME", None),
            "business_id": getattr(business, "BUSINESS_ID", None),
            "payer_info_id": getattr(business, "PAYER_INFO_ID", None),
            "availity_payer_no": getattr(payer_info, "AVAILITY_PAYER_NO", None),
            "elg_enrollment": getattr(payer_info, "ELG_ENROLLMENT", None),
            "elg_clearinghouse": getattr(payer_info, "ELG_CLEARINGHOUSE", None),
        })
    return result


@router.post("/patients/{patient_id}/duplicate-check")
def duplicate_check(
    patient_id: int,
    db: Session = Depends(get_claims_db),
):
    repo = ClaimsRepository(db)
    patient = repo.get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    candidates = repo.find_duplicate_patients(patient)
    return {
        "patient_id": patient_id,
        "has_duplicates": len(candidates) > 0,
        "candidates": [
            {
                "patient_id": c.PATIENT_ID,
                "first_name": c.FIRST_NAME,
                "last_name": c.LAST_NAME,
                "dob": str(c.DOB) if c.DOB else None,
                "mrn": c.MRN,
            }
            for c in candidates
        ],
    }


@router.get("/patients/{patient_id}/insurance-image-check")
def has_insurance_image(
    patient_id: int,
    clinic_id: int = Query(...),
    db: Session = Depends(get_claims_db),
):
    repo = ClaimsRepository(db)
    has_image = repo.has_insurance_image_in_claims(patient_id, clinic_id)
    return {"patient_id": patient_id, "has_insurance_image": has_image}


# ═══════════════════════════════════════════════════════════════════════════════
# Claims (read from allofactorv3)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/claims/charges/new")
def get_new_charges(
    limit: int = Query(100, le=500),
    db: Session = Depends(get_claims_db),
    _: None = Depends(_verify_internal),
):
    return ClaimsRepository(db).find_new_charges(limit=limit)


@router.get("/claims/{claim_id}")
def get_claim(
    claim_id: int,
    db: Session = Depends(get_claims_db),
):
    claim = ClaimsRepository(db).get_claim(claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return {
        "claim_id": claim.CLAIM_ID,
        "clinic_id": claim.CLINIC_ID,
        "patient_id": claim.PATIENT_ID,
        "provider_id": claim.PROVIDER_ID,
        "visit_id": claim.VISIT_ID,
        "facility_id": claim.FACILITY_ID,
        "dos": str(claim.DOS) if claim.DOS else None,
        "billing_method": claim.BILLING_METHOD,
        "status": claim.STATUS,
        "primary_payer_id": claim.PRIMARY_PAYER_ID,
        "primary_insurance_id": claim.PRIMARY_INSURANCE_ID,
    }


@router.get("/facilities/{facility_id}")
def get_facility(
    facility_id: int,
    db: Session = Depends(get_claims_db),
):
    facility = ClaimsRepository(db).get_facility(facility_id)
    if not facility:
        raise HTTPException(status_code=404, detail="Facility not found")
    return {
        "facility_id": facility.FACILITY_ID,
        "clinic_id": facility.CLINIC_ID,
        "facility_name": facility.FACILITY_NAME,
        "phone": facility.PHONE,
        "fax": facility.FAX,
        "npi": facility.NPI,
        "pos": facility.POS,
        "address_line1": facility.ADDRESS_LINE1,
        "city": facility.CITY,
        "state": facility.STATE,
        "zip": facility.ZIP,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Profile Engine
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/profile/facilities/{facility_id}/emr-access")
def get_emr_access(
    facility_id: int,
    clinic_id: int | None = Query(None),
    claims_db: Session = Depends(get_claims_db),
):
    """
    Determine whether we have direct EMR access to this facility.
    Checks CLINIC_MASTER first, then external profile engine.
    """
    claims_repo = ClaimsRepository(claims_db) if clinic_id else None
    svc = ProfileEngineService()
    result = svc.get_emr_access(
        facility_id=facility_id,
        clinic_id=clinic_id,
        claims_repo=claims_repo,
    )
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# OCR
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/ocr/extract")
def extract_ocr(
    payload: DocumentOCRRequest,
    db: Session = Depends(get_workflow_db),
    _: None = Depends(_verify_internal),
):
    """
    Run OCR on a document stored in S3.
    Updates RCM_DOCUMENT.ocr_text and status_code after extraction.
    """
    repo = WorkflowRepository(db)
    doc = repo.get_document(payload.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    result = OCRService().extract_from_s3(
        bucket=doc.s3_bucket,
        key=doc.s3_key,
        mode=payload.mode,
        document_id=payload.document_id,
    )
    repo.update_document_ocr(
        payload.document_id,
        ocr_text=result.get("ocr_text", ""),
        status_code="OCR_COMPLETE" if result.get("ocr_text") else "OCR_EMPTY",
    )
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# LLM
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/llm/insurance-parse")
def parse_insurance(
    document_id: int,
    db: Session = Depends(get_workflow_db),
    _: None = Depends(_verify_internal),
):
    """
    Run LLM extraction on the OCR text already stored in RCM_DOCUMENT.
    Returns structured insurance fields.
    """
    doc = WorkflowRepository(db).get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.ocr_text:
        raise HTTPException(status_code=400, detail="Document has no OCR text; run /ocr/extract first")

    mode = doc.document_type.lower()
    svc = LLMService()
    if "facesheet" in mode:
        result = svc.parse_facesheet(doc.ocr_text, document_id=document_id)
    else:
        result = svc.parse_insurance_card(doc.ocr_text, document_id=document_id)
    return result


@router.post("/llm/classify-document")
def classify_document(
    document_id: int,
    db: Session = Depends(get_workflow_db),
    _: None = Depends(_verify_internal),
):
    doc = WorkflowRepository(db).get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.ocr_text:
        raise HTTPException(status_code=400, detail="No OCR text available")
    label = LLMService().classify_document(doc.ocr_text)
    return {"document_id": document_id, "classification": label}


# ═══════════════════════════════════════════════════════════════════════════════
# Eligibility
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/eligibility/verify")
def verify_eligibility(
    payload: EligibilityVerifyRequest,
    db: Session = Depends(get_workflow_db),
    _: None = Depends(_verify_internal),
):
    """
    Call the Availity clearinghouse and persist the result in RCM_ELIGIBILITY_RESULT.
    Also writes eligibility facts to RCM_FACT.
    """
    svc = EligibilityService()
    result = svc.verify(payload.model_dump())

    repo = WorkflowRepository(db)

    # Persist eligibility result row
    elg_row = repo.create_eligibility_result(
        EligibilityResultCreate(
            case_id=payload.case_id,
            patient_id=payload.patient_id,
            insurance_id=payload.insurance_id,
            verification_mode="ELECTRONIC",
            clearinghouse_name=result.get("clearinghouse_name", "AVAILITY"),
            payer_number=result.get("payer_number"),
            coverage_status=result.get("coverage_status"),
            copay_amount=result.get("copay_amount"),
            coinsurance_percent=result.get("coinsurance_percent"),
            deductible_amount=result.get("deductible_amount"),
            deductible_remaining_amount=result.get("deductible_remaining_amount"),
            out_of_pocket_amount=result.get("out_of_pocket_amount"),
            plan_begin_date=result.get("plan_begin_date"),
            plan_end_date=result.get("plan_end_date"),
            subscriber_first_name=result.get("subscriber_first_name"),
            subscriber_last_name=result.get("subscriber_last_name"),
            raw_request_json=result.get("raw_request_json"),
            raw_response_json=result.get("raw_response_json"),
            normalized_json=result.get("normalized_json"),
            result_code=result.get("result_code", "UNKNOWN"),
            result_note=result.get("result_note"),
        )
    )

    # Write key facts
    facts = [
        FactCreate(
            case_id=payload.case_id,
            fact_scope=FACT_SCOPE_ELIGIBILITY,
            fact_key="coverage_status",
            fact_value_str=result.get("coverage_status"),
            source_system="AVAILITY",
        ),
        FactCreate(
            case_id=payload.case_id,
            fact_scope=FACT_SCOPE_ELIGIBILITY,
            fact_key="eligibility_result_id",
            fact_value_str=str(elg_row.eligibility_result_id),
            source_system="AVAILITY",
        ),
    ]
    repo.bulk_create_facts(facts)

    return {
        "eligibility_result_id": elg_row.eligibility_result_id,
        **result,
    }


@router.get("/eligibility/cases/{case_id}/latest")
def get_latest_eligibility(
    case_id: int,
    insurance_id: int | None = Query(None),
    db: Session = Depends(get_workflow_db),
):
    row = WorkflowRepository(db).get_latest_eligibility_result(case_id, insurance_id)
    if not row:
        raise HTTPException(status_code=404, detail="No eligibility result found for case")
    return {
        "eligibility_result_id": row.eligibility_result_id,
        "coverage_status": row.coverage_status,
        "result_code": row.result_code,
        "result_note": row.result_note,
        "copay_amount": row.copay_amount,
        "deductible_amount": row.deductible_amount,
        "created_at": row.created_at,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Serialisation helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _case_to_response(row) -> CaseResponse:
    return CaseResponse(
        case_id=row.case_id,
        state_code=row.state_code,
        substate_code=row.substate_code,
        patient_id=row.patient_id,
        charge_id=row.charge_id,
        claim_id=row.claim_id,
        clinic_id=row.clinic_id,
        facility_id=row.facility_id,
        next_action_at=row.next_action_at,
        terminal_outcome_code=row.terminal_outcome_code,
        context_json=row.context_json,
    )


def _task_dict(t) -> dict:
    return {
        "task_id": t.task_id,
        "case_id": t.case_id,
        "task_type": t.task_type,
        "intent_key": t.intent_key,
        "state_code": t.state_code,
        "queue_id": t.queue_id,
        "handler_key": t.handler_key,
        "attempt_count": t.attempt_count,
        "next_action_at": t.next_action_at,
        "payload_json": t.payload_json,
    }


def _patient_dict(p) -> dict:
    return {
        "patient_id": p.PATIENT_ID,
        "clinic_id": p.CLINIC_ID,
        "facility_id": p.FACILITY_ID,
        "first_name": p.FIRST_NAME,
        "last_name": p.LAST_NAME,
        "middle_name": p.MIDDLE_NAME,
        "dob": str(p.DOB) if p.DOB else None,
        "sex": p.SEX,
        "mrn": p.MRN,
        "address_line1": p.ADDRESS_LINE1,
        "city": p.CITY,
        "state": p.STATE,
        "zip": p.ZIP,
        "phone": p.PHONE,
        "mobile": p.MOBILE,
        "email": p.EMAIL,
        "billing_method": p.BILLING_METHOD,
        "is_self_pay": p.BILLING_METHOD == 0,
        "active": p.ACTIVE,
        "is_deceased": p.IS_DECEASED,
    }
