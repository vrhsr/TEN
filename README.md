# Demographics Agent

AI-driven front-end revenue cycle workflow that validates patient demographics
and insurance before claim creation.

## Architecture

```
Temporal (workflow layer)
    └── advance_case activity
            │
            ▼
Orchestration Service  (LangGraph)        port 8002
    ├── DEMO_INITIALIZE
    ├── DEMO_GATHER_REGISTRATION
    ├── DEMO_VERIFY_REGISTRATION
    ├── DEMO_VERIFY_ELIGIBILITY
    ├── DEMO_SELF_REGISTRATION
    ├── DEMO_HOSPITAL_FACESHEET_REQUEST
    └── DEMO_NORMALIZE_CASE
            │  (all DB and external calls via HTTP)
            ▼
Tools Service  (FastAPI)                  port 8001
    ├── allofactorv3 MySQL  (read + targeted writes)
    ├── rcm_workflow MySQL  (all workflow state)
    ├── AWS S3              (document storage)
    ├── Availity            (eligibility 270/271)
    ├── OpenAI              (LLM insurance extraction)
    ├── Tesseract OCR       (document text extraction)
    └── Profile Engine      (facility EMR access check)

Scheduler / Workflow Service              (APScheduler process)
    ├── charge_intake_job   (polls CLAIM table every 60s)
    └── timer_wakeup_job    (wakes due cases every 30s)
```

## Workflow States

| State | Meaning |
|---|---|
| `CLAIM_INITIALIZE` | New case; run initialize handler |
| `START_REGISTRATION_QUEUE` | Demographics or insurance missing |
| `VERIFY_REGISTRATION_INFO_QUEUE` | Human confirms document is correct |
| `ELIGIBILITY_VERIFICATION_QUEUE` | Run Availity electronic check |
| `SELF_REGISTRATION_QUEUE` | Patient outreach (SMS/voice) |
| `HOSPITAL_FACESHEET_FAX_QUEUE` | Fax request to hospital |
| `HOSPITAL_FACESHEET_DOWNLOAD_QUEUE` | Human downloads from EMR |
| `CLINIC_INSURANCE_IMAGE_DOWNLOAD_QUEUE` | Human checks clinic EMR |
| `FIX_ELIGIBILITY_ERROR_QUEUE` | Human corrects bad document/data |
| `MANUAL_ELIGIBILITY_VERIFICATION_QUEUE` | Manual eligibility (WC/auto/PI) |
| `PATIENT_DEDUPLICATION_QUEUE` | Human resolves duplicate patient |
| `FACESHEET_NOT_RECEIVED_COORDINATOR_QUEUE` | Escalation after 3 fax attempts |
| `SELF_REGISTRATION_NOT_RECEIVED_COORDINATOR_QUEUE` | Escalation after 3 patient attempts |
| **`CASE_CLOSED_SELF_PAY`** | Terminal — self-pay patient |
| **`CASE_READY_FOR_CLAIM_CREATION`** | Terminal — claim-ready |

## Quick Start

```bash
# 1. Bootstrap
bash scripts/bootstrap.sh

# 2. Configure
vi .env   # fill in DB credentials, OpenAI key, Availity credentials, S3 bucket

# 3. Start services (3 separate terminals)
uvicorn services.tools_service.app.main:app --port 8001 --reload
uvicorn services.orchestration_service.app.main:app --port 8002 --reload
python -m services.workflow_service.app.workers.scheduler
```

## Database Mapping (allofactorv3)

| Purpose | Table | Key field |
|---|---|---|
| Patient demographics | `PATIENT` | `BILLING_METHOD=0` → self-pay |
| Insurance policies | `INSURANCE` | `RANKING` 1=primary, 2=secondary |
| Payer / insurer master | `BUSINESS` | `PAYER_INFO_ID` → `PAYER_INFO` |
| Clearinghouse payer IDs | `PAYER_INFO` | `AVAILITY_PAYER_NO` |
| Facility / hospital | `FACILITY` | `FAX` used for fax outreach |
| Clinic configuration | `CLINIC_MASTER` | `TYPE=50` → direct EMR access |
| Claims (charge intake) | `CLAIM` | `STATUS=1, READY_TO_SENT=0` |

## Key Integration Points

- **Self-pay detection**: `PATIENT.BILLING_METHOD = 0`
- **Payer linkage**: `INSURANCE.COMPANY_ID → BUSINESS.BUSINESS_ID → BUSINESS.PAYER_INFO_ID → PAYER_INFO.PAYER_INFO_ID`
- **Availity payer number**: `PAYER_INFO.AVAILITY_PAYER_NO`
- **Direct EMR access**: `CLINIC_MASTER TYPE=50` row where `VALUE = facility_id`
- **Eligibility freshness**: configurable via `ELIGIBILITY_FRESHNESS_DAYS` (default 30 days)

## Enabling Real Temporal

1. `pip install temporalio`
2. Set `TEMPORAL_HOST=localhost:7233` in `.env`
3. Run `python -m services.workflow_service.app.workers.temporal_worker_stub`
4. Disable `timer_wakeup_job` in `scheduler.py` (Temporal handles timers natively)
