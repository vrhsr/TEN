from datetime import datetime
from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    case_id: int
    task_type: str
    intent_key: str
    state_code: str = "OPEN"
    priority_code: str = "normal"
    priority_rank: int = 100
    queue_id: str | None = None
    handler_key: str | None = None
    next_action_at: datetime | None = None
    due_at: datetime | None = None
    attempt_count: int = 0
    payload_json: dict = Field(default_factory=dict)


class TaskUpdate(BaseModel):
    state_code: str | None = None
    close_reason_code: str | None = None
    result_json: dict | None = None
    next_action_at: datetime | None = None
    due_at: datetime | None = None
    attempt_count: int | None = None
    payload_json: dict | None = None
