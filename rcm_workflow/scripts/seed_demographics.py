import requests
import json
from datetime import datetime, timezone

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
BASE_URL = "https://app.staging.trillium.health/temporal-rcm-workflow"
ENDPOINT = "/api/v1/workflow-engine/cases/create"
URL = BASE_URL + ENDPOINT

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    # "Authorization": "Bearer YOUR_TOKEN_HERE",  # Uncomment if needed
}

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ─────────────────────────────────────────────
# Source Data — each section stored as one fact
# ─────────────────────────────────────────────
PATIENT_INFO = {
    "PATIENT_ID":5,
    "CLINIC_ID": 83622,
    "FIRST_NAME": "yuvaraj",
    "MIDDLE_NAME": "M",
    "LAST_NAME": "FrankRe",
    "DOB": "1966-07-08",
    "GENDER": "M"
}

CLAIM_CORE_INFO = {
    "CLAIM_ID":    None,
    "DOS":         "2026-04-10",
    "PROVIDER_ID": None,
    "LOCATION_ID": None,
    "FACILITY_ID": None,
}

INSURANCE_INFO = {
    "PAYER_ID":        "PAY-999",
    "POLICY_ID":       "POL-123456",
    "GROUP_NUMBER":    "GRP-789",
    "RELATION_TO_SUB": "Self",
}


ORCHESTRATION_INFO = {
    "SELF_PAY_FLAG":               False,
    "HAS_INSURANCE":               True,
    "DEMOGRAPHICS_COMPLETE":       True,
    "DUPLICATE_FLAG":              False,
    "LAST_ELIGIBILITY_CHECK_DATE": "2025-01-01", # <-- Older than 30 days (or None)
    "PLACE_OF_SERVICE":            "clinic",
}
# ─────────────────────────────────────────────
# Build facts — one fact per section,
# entire section stored as a JSON string in fact_value_str
# ─────────────────────────────────────────────
def make_json_fact(fact_key: str, data: dict, source: str = "ehr_system") -> dict:
    return {
        "fact_key":        fact_key,
        "fact_value_str":  json.dumps(data),   # section stored as JSON string
        "fact_value_num":  None,
        "fact_value_bool": None,
        "fact_value_date": None,
        "source":          source,
    }


facts = [
    make_json_fact("PATIENT_INFO",       PATIENT_INFO),
    make_json_fact("CLAIM_CORE_INFO",    CLAIM_CORE_INFO),
    make_json_fact("INSURANCE_INFO",     INSURANCE_INFO),
    make_json_fact("ORCHESTRATION_INFO", ORCHESTRATION_INFO),
]


# ─────────────────────────────────────────────
# Request Payload
# ─────────────────────────────────────────────
payload = {
    "clinic_id":         PATIENT_INFO["CLINIC_ID"],
    "case_type":         "DEMOGRAPHICS",
    "state_code":        "DEMOGRAPHICS_CREATED",
    "workflow_version":  "v1",
    "claim_id":          CLAIM_CORE_INFO["CLAIM_ID"],
    "patient_id":        PATIENT_INFO["PATIENT_ID"],
    "facility_id":       CLAIM_CORE_INFO["FACILITY_ID"],
    "provider_id":       CLAIM_CORE_INFO["PROVIDER_ID"],
    "payer_id":          None,
    "substate_code":     "pending",
    "queue_id":          "default-queue",
    "owner_user_id":     5,
    "owner_user_name":   "john.doe",
    "current_task_id":   0,
    "current_task_type": "review",
    "due_at":            NOW,
    "facts":             facts,
}


# ─────────────────────────────────────────────
# API Call
# ─────────────────────────────────────────────
def create_case(payload: dict) -> dict:
    """Call the Create Case API and return the response."""
    try:
        response = requests.post(URL, headers=HEADERS, json=payload, timeout=30)
        response.raise_for_status()
        print(f"✅ Success! Status code: {response.status_code}")
        return response.json()

    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP Error: {e.response.status_code} - {e.response.text}")
    except requests.exceptions.ConnectionError:
        print("❌ Connection Error: Could not reach the server.")
    except requests.exceptions.Timeout:
        print("❌ Timeout: The request timed out.")
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")

    return {}


if __name__ == "__main__":
    print(f"📤 Sending POST request to: {URL}\n")

    print("📦 Facts being sent:")
    for f in facts:
        print(f"\n  [{f['fact_key']}]")
        print(f"  {f['fact_value_str']}")

    print(f"\n📦 Full Payload:\n{json.dumps(payload, indent=2)}\n")

    result = create_case(payload)

    if result:
        print(f"\n📥 Response:\n{json.dumps(result, indent=2)}")