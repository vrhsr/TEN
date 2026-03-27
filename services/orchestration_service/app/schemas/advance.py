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


class AdvanceCaseOutput(BaseModel):
    case_id: int
    handler_key: str
    state_before: str | None = None
    state_after: str | None = None
    outcome_code: str | None = None
    note: str | None = None
    next_wake_at: str | None = None
    confidence_score: float | None = None
    tools_invoked: list[str] = Field(default_factory=list)
    emit_events: list[dict] = Field(default_factory=list)
