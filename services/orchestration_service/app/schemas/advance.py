from datetime import datetime
from pydantic import BaseModel, Field


class AdvanceTrigger(BaseModel):
    type: str = "TIMER"          # TIMER | EVENT | MANUAL | SIGNAL
    correlation_id: str
    task_id: int | None = None   # RCM_TASK id supplied by caller (Temporal / scheduler)
    event_type: str | None = None
    payload: dict = Field(default_factory=dict)



class AdvanceTaskInput(BaseModel):
    task_id: int


class AdvanceCaseInput(BaseModel):
    case_id: int
    trigger: AdvanceTrigger


class AdvanceOutcome(BaseModel):
    outcome_code: str | None = None
    note: str | None = None

class AdvancePayload(BaseModel):
    case_id: int
    task_id: int | None = None
    outcome: AdvanceOutcome
    existing_facts: dict = Field(default_factory=dict)
    payload_updated: bool = True
    extracted_entities: dict | None = None
    confidence_score: float | None = None

class AdvanceData(BaseModel):
    payload: AdvancePayload

class AdvanceCaseResponse(BaseModel):
    success: bool = True
    code: int = 200
    data: AdvanceData
