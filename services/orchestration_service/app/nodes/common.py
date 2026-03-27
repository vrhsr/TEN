from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def build_result(
    state: dict,
    handler_key: str,
    next_state: str,
    next_wake_at: str | None = None,
    outcome_code: str = "ADVANCED",
    note: str | None = None,
    confidence_score: float = 1.0,
    facts_considered: dict | None = None,
    tools_invoked: list[str] | None = None,
    node_count: int = 1,
    **extra: Any,
) -> dict:
    """
    Construct the standardized result dict returned by every handler node.
    The engine reads this to update RCM_CASE and write RCM_STEP_HISTORY.
    """
    return {
        "handler_key": handler_key,
        "next_state": next_state,
        "next_wake_at": next_wake_at,
        "outcome_code": outcome_code,
        "note": note,
        "confidence_score": confidence_score,
        "facts_considered": facts_considered or {},
        "tools_invoked": tools_invoked or [],
        "node_count": node_count,
        **extra,
    }


def iso_offset(minutes: int = 0, hours: int = 0, days: int = 0) -> str:
    """Return an ISO-8601 UTC datetime string offset from now."""
    dt = datetime.now(timezone.utc) + timedelta(
        minutes=minutes, hours=hours, days=days,
    )
    return dt.isoformat()


# Default required demographic fields for claim creation
_DEFAULT_REQUIRED_DEMOGRAPHICS = [
    "first_name",
    "last_name",
    "dob",
    "address_line1",
    "zip",
]


def is_demographics_complete(
    patient: dict,
    required_fields: list[str] | None = None,
) -> bool:
    """
    Minimum required fields for a patient record to be considered
    demographically complete for claim creation.

    Pass required_fields to override per-tenant requirements.
    """
    fields = required_fields or _DEFAULT_REQUIRED_DEMOGRAPHICS
    return all(bool(patient.get(f)) for f in fields)


def is_insurance_present(insurances: list[dict]) -> bool:
    """
    Check if at least one active insurance record exists.

    Looks for either 'active' or 'is_active' field being True,
    depending on the claims system's field naming convention.
    """
    if not insurances:
        return False
    return any(
        ins.get("active", False) or ins.get("is_active", False)
        for ins in insurances
    )


def get_primary_insurance(insurances: list[dict]) -> dict | None:
    """
    Return the primary insurance (ranking=1).
    Falls back to the first insurance record if no explicit ranking exists.
    Returns None if no insurance records exist.
    """
    primary = [i for i in insurances if i.get("ranking") == 1]
    if primary:
        return primary[0]
    return insurances[0] if insurances else None