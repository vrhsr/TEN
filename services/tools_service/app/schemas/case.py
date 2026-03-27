from datetime import datetime
from pydantic import BaseModel, Field


class CaseCreate(BaseModel):
    case_type: str
    workflow_name: str
    workflow_version: str = "v1"
    claim_id: int | None = None
    clinic_id: int | None = None
    facility_id: int | None = None
    provider_id: int | None = None
    patient_id: int | None = None
    payer_id: int | None = None
    visit_id: int | None = None
    charge_id: int | None = None
    state_code: str
    context_json: dict = Field(default_factory=dict)


class CaseUpdate(BaseModel):
    state_code: str | None = None
    substate_code: str | None = None
    step_code: str | None = None
    queue_id: str | None = None
    current_task_id: int | None = None
    next_action_at: datetime | None = None
    due_at: datetime | None = None
    context_json: dict | None = None
    terminal_outcome_code: str | None = None
    closed_at: datetime | None = None


class CaseEvent(BaseModel):
    event_type: str
    event_time: datetime
    correlation_id: str
    payload: dict = Field(default_factory=dict)


class CaseAdvanceTrigger(BaseModel):
    type: str = "TIMER"
    correlation_id: str
    event_type: str | None = None


class CaseAdvanceRequest(BaseModel):
    trigger: CaseAdvanceTrigger


class CaseResponse(BaseModel):
    case_id: int
    state_code: str
    substate_code: str | None = None
    patient_id: int | None = None
    charge_id: int | None = None
    claim_id: int | None = None
    clinic_id: int | None = None
    facility_id: int | None = None
    next_action_at: datetime | None = None
    terminal_outcome_code: str | None = None
    context_json: dict | None = None

    class Config:
        from_attributes = True
