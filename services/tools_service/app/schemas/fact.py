from pydantic import BaseModel


class FactCreate(BaseModel):
    case_id: int
    fact_scope: str
    fact_key: str
    fact_value_str: str | None = None
    fact_value_num: float | None = None
    fact_value_bool: bool | None = None
    source_system: str | None = None
    source_ref: str | None = None
    confidence_score: float | None = None
    is_current: bool = True


class FactsBulkCreate(BaseModel):
    case_id: int
    facts: list[FactCreate]
