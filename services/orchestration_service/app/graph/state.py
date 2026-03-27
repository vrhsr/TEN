from typing import Any, TypedDict


class DemoGraphState(TypedDict, total=False):
    # Core case context (loaded at the start of every advance_case call)
    case: dict                          # RCM_CASE row as dict
    patient: dict                       # PATIENT row as dict
    insurances: list[dict]              # INSURANCE rows enriched with payer info
    facility: dict | None               # FACILITY row as dict
    open_tasks: list[dict]              # RCM_TASK rows (open)
    facts: dict[str, str]               # fact_key → fact_value_str (current facts)

    # Intermediate decisioning outputs
    has_duplicate: bool
    duplicate_candidates: list[dict]
    is_self_pay: bool
    has_insurance_image: bool
    has_direct_emr_access: bool
    emr_system: str | None

    # Eligibility outputs
    eligibility_result: dict | None
    ocr_result: dict | None
    llm_result: dict | None

    # Handler resolution
    selected_handler: str
    handler_version: str

    # Final outputs written back by engine
    next_state: str
    next_wake_at: str | None           # ISO-8601 datetime string
    outcome_code: str
    handler_key: str
    note: str | None
    facts_considered: dict[str, Any]
    tools_invoked: list[str]
    confidence_score: float

    # Error tracking
    error: str | None
