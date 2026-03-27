from datetime import datetime
from pydantic import BaseModel


class StepHistoryCreate(BaseModel):
    case_id: int
    correlation_id: str
    trigger_type: str
    handler_key: str
    handler_version: str = "v1"
    state_before: str | None = None
    state_after: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    outcome_code: str
    facts_considered_json: dict | None = None
    tools_invoked_json: dict | None = None
    confidence_score: float | None = None
    output_summary_json: dict | None = None
    error_detail: str | None = None
