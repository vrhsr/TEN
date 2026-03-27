from datetime import datetime
from pydantic import BaseModel


class EligibilityVerifyRequest(BaseModel):
    case_id: int
    patient_id: int
    insurance_id: int | None = None
    clearinghouse: str = "AVAILITY"
    payer_info_id: int | None = None
    payer_number: str | None = None
    request_payload: dict | None = None


class EligibilityResultCreate(BaseModel):
    case_id: int
    patient_id: int
    insurance_id: int | None = None
    verification_mode: str
    clearinghouse_name: str | None = None
    payer_number: str | None = None
    coverage_status: str | None = None
    copay_amount: float | None = None
    coinsurance_percent: float | None = None
    deductible_amount: float | None = None
    deductible_remaining_amount: float | None = None
    family_deductible_amount: float | None = None
    family_deductible_remaining_amount: float | None = None
    out_of_pocket_amount: float | None = None
    out_of_pocket_remaining: float | None = None
    plan_begin_date: datetime | None = None
    plan_end_date: datetime | None = None
    subscriber_first_name: str | None = None
    subscriber_last_name: str | None = None
    subscriber_dob: datetime | None = None
    raw_request_json: dict | None = None
    raw_response_json: dict | None = None
    normalized_json: dict | None = None
    result_code: str
    result_note: str | None = None
