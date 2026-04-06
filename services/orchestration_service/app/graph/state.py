# graph/state.py

from typing import TypedDict, Optional, List, Any


class DemographicsAgentState(TypedDict):

    # ─────────────────────────────────────
    # Case & Task Identifiers
    # ─────────────────────────────────────
    case_id         : int
    task_id         : int
    clinic_id       : int

    # ─────────────────────────────────────
    # Facts Loaded from RCM_CASE_FACT
    # ─────────────────────────────────────
    patient_fact        : Optional[dict]
    insurance_fact      : Optional[dict]
    demographics_fact   : Optional[dict]

    # ─────────────────────────────────────
    # Task + Case Details
    # ─────────────────────────────────────
    task_details    : Optional[dict]
    case_details    : Optional[dict]

    # ─────────────────────────────────────
    # Node 2: Duplicate Check
    # ─────────────────────────────────────
    is_duplicate            : bool
    duplicate_patient_ids   : Optional[List[int]]   # list of duplicate patient IDs found
    duplicate_reason        : Optional[str]         # reason why flagged as duplicate

    # ─────────────────────────────────────
    # Node 3: Decision Flags
    # ─────────────────────────────────────
    is_self_pay             : bool
    demographics_complete   : bool
    insurance_verified      : bool
    days_since_verified     : Optional[int]

    # ─────────────────────────────────────
    # Routing
    # ─────────────────────────────────────
    next_queue          : Optional[str]
    next_state_code     : Optional[str]

    # ─────────────────────────────────────
    # Payload to store in RCM_TASK
    # ─────────────────────────────────────
    task_payload        : Optional[dict]

    # ─────────────────────────────────────
    # Audit / Explainability
    # ─────────────────────────────────────
    facts_considered    : Optional[List[str]]
    tools_invoked       : Optional[List[str]]
    confidence_score    : Optional[float]
    decision_reason     : Optional[str]

    # ─────────────────────────────────────
    # Error Handling
    # ─────────────────────────────────────
    error           : Optional[str]
    attempt_count   : int