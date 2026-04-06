# orchestration_service/app/clients/tools_client.py
from __future__ import annotations

import json
import os
import pymysql
import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from shared.config import get_settings
from shared.logging import get_logger

log = get_logger(__name__)


def _raise_on_4xx_5xx(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise httpx.HTTPStatusError(
            f"Tools API {response.status_code}: {response.text[:300]}",
            request=response.request,
            response=response,
        )


class ToolsClient:

    def __init__(self) -> None:
        settings       = get_settings()
        self._base_url = settings.tools_base_url
        self._secret   = settings.internal_api_secret

        print(f"\n{'='*60}")
        print(f"   ToolsClient BASE URL : {self._base_url}")
        print(f"{'='*60}\n")

        self._http = httpx.Client(
            base_url=self._base_url,
            timeout=30.0,
            headers={
                "Content-Type": "application/json",
                "x-api-secret": self._secret,
            },
        )

    # ══════════════════════════════════════════════════════════════════
    # TASK — API
    # ══════════════════════════════════════════════════════════════════

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def get_task_and_case(self, task_id: int) -> dict:
        url = f"/api/v1/workflow-engine/{task_id}/rcm_task_and_rcm_case"
        print(f"\n   get_task_and_case → Calling: {self._base_url}{url}")

        r = self._http.get(url)
        print(f"   get_task_and_case → Status : {r.status_code}")
        print(f"   get_task_and_case → Response: {r.text[:300]}")

        _raise_on_4xx_5xx(r)
        return r.json()["data"]

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def update_task(self, task_id: int, payload: dict) -> dict:
        url = f"/api/v1/workflow-engine/{task_id}/rcm_task/process"
        r   = self._http.post(url, json={"payload": payload})
        _raise_on_4xx_5xx(r)
        return r.json()

    def create_task(self, payload: dict) -> dict:
        r = self._http.post("/api/v1/workflow-engine/start", json=payload)
        _raise_on_4xx_5xx(r)
        return r.json()

    # ══════════════════════════════════════════════════════════════════
    # TASK — DIRECT DB LOOKUP                ← ✅ STILL INSIDE CLASS
    # ══════════════════════════════════════════════════════════════════

    # app/clients/tools_client.py

    def get_task_from_db(self, task_id: int) -> dict | None:
        """
        Direct DB lookup for RCM_TASK.
        Uses pydantic Settings (reads .env correctly).
        """
        settings = get_settings()                   # ← already imported at top

        host     = settings.rcm_db_host
        port     = settings.rcm_db_port
        user     = settings.rcm_db_user
        password = settings.rcm_db_password
        database = settings.rcm_db_database

        print(f"\n   get_task_from_db → Connecting to DB")
        print(f"   get_task_from_db → host    : {host}:{port}")
        print(f"   get_task_from_db → user    : {user}")
        print(f"   get_task_from_db → password: {'SET ✅' if password else 'EMPTY ❌'}")
        print(f"   get_task_from_db → database: {database}")
        print(f"   get_task_from_db → task_id : {task_id}")

        try:
            conn = pymysql.connect(
                host            = host,
                port            = port,
                user            = user,
                password        = password,
                database        = database,
                cursorclass     = pymysql.cursors.DictCursor,
                connect_timeout = 10,
            )
        except Exception as exc:
            log.error("get_task_from_db.connect_failed", error=str(exc))
            raise

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        RCM_TASK_ID,
                        RCM_CASE_ID,
                        CLINIC_ID,
                        TASK_TYPE,
                        STATE_CODE,
                        QUEUE_ID,
                        PRIORITY_CODE,
                        HANDLER_KEY,
                        PAYLOAD_JSON,
                        RESULT_JSON,
                        OUTCOME,
                        ATTEMPT_COUNT,
                        OPENED_AT,
                        DUE_AT,
                        CREATED_AT,
                        UPDATED_AT
                    FROM RCM_TASK
                    WHERE RCM_TASK_ID = %s
                    LIMIT 1
                    """,
                    (task_id,),
                )
                row = cur.fetchone()

                if not row:
                    print(f"   get_task_from_db → Task {task_id} NOT found in DB ❌")
                    return None

                print(
                    f"   get_task_from_db → Found task {task_id} "
                    f"→ case_id={row['RCM_CASE_ID']} ✅"
                )

                return {
                    "task_id"      : row["RCM_TASK_ID"],
                    "rcm_task_id"  : row["RCM_TASK_ID"],
                    "rcm_case_id"  : row["RCM_CASE_ID"],
                    "case_id"      : row["RCM_CASE_ID"],
                    "clinic_id"    : row["CLINIC_ID"],
                    "task_type"    : row["TASK_TYPE"],
                    "state_code"   : row["STATE_CODE"],
                    "queue_id"     : row["QUEUE_ID"],
                    "priority_code": row["PRIORITY_CODE"],
                    "handler_key"  : row["HANDLER_KEY"],
                    "payload_json" : row["PAYLOAD_JSON"],
                    "result_json"  : row["RESULT_JSON"],
                    "outcome"      : row["OUTCOME"],
                    "attempt_count": row["ATTEMPT_COUNT"],
                    "opened_at"    : str(row["OPENED_AT"])  if row["OPENED_AT"]  else None,
                    "due_at"       : str(row["DUE_AT"])     if row["DUE_AT"]     else None,
                    "created_at"   : str(row["CREATED_AT"]) if row["CREATED_AT"] else None,
                    "updated_at"   : str(row["UPDATED_AT"]) if row["UPDATED_AT"] else None,
                }
        finally:
            conn.close()

    # ══════════════════════════════════════════════════════════════════
    # CASE                                   ← ✅ STILL INSIDE CLASS
    # ══════════════════════════════════════════════════════════════════

    def get_case(self, case_id: int) -> dict | None:
        try:
            url = "/api/v1/workflow-engine/cases"
            print(f"\n   get_case → Calling: {self._base_url}{url}")

            r = self._http.get(url)
            print(f"   get_case → Status : {r.status_code}")

            _raise_on_4xx_5xx(r)
            data  = r.json()
            cases = data.get("data", {}).get("cases", [])

            print(f"   get_case → Total cases: {len(cases)}")

            for c in cases:
                if c.get("RCM_CASE_ID") == case_id:
                    print(f"   get_case → Found case: {case_id}")
                    return {
                        "case_id"          : c["RCM_CASE_ID"],
                        "rcm_case_id"      : c["RCM_CASE_ID"],
                        "clinic_id"        : c.get("CLINIC_ID"),
                        "patient_id"       : c.get("PATIENT_ID"),
                        "case_type"        : c.get("CASE_TYPE"),
                        "workflow_name"    : c.get("WORKFLOW_NAME"),
                        "workflow_version" : c.get("WORKFLOW_VERSION"),
                        "state_code"       : c["STATE_CODE"],
                        "substate_code"    : c.get("SUBSTATE_CODE"),
                        "queue_id"         : c.get("QUEUE_ID"),
                        "claim_id"         : c.get("CLAIM_ID"),
                        "facility_id"      : c.get("FACILITY_ID"),
                        "provider_id"      : c.get("PROVIDER_ID"),
                        "payer_id"         : c.get("PAYER_ID"),
                        "current_task_id"  : c.get("CURRENT_TASK_ID"),
                        "current_task_type": c.get("CURRENT_TASK_TYPE"),
                        "created_at"       : c.get("CREATED_AT"),
                        "updated_at"       : c.get("UPDATED_AT"),
                        "context_json"     : {},
                    }

            print(f"   get_case → Case {case_id} NOT found in list")
            return None

        except Exception as exc:
            log.error("tools_client.get_case.failed", case_id=case_id, error=str(exc))
            return None

    def update_case(self, case_id: int, payload: dict) -> dict:
        log.info("tools_client.update_case", case_id=case_id)
        return {"updated": True, "case_id": case_id}

    # ══════════════════════════════════════════════════════════════════
    # FACTS
    # ══════════════════════════════════════════════════════════════════

    def get_case_facts(self, case_id: int) -> list[dict]:
        url = f"/api/v1/workflow-engine/cases/{case_id}/facts"
        print(f"\n   get_case_facts → Calling: {self._base_url}{url}")

        r = self._http.get(url)
        print(f"   get_case_facts → Status : {r.status_code}")

        if r.status_code == 404:
            print(f"   get_case_facts → No facts found for case {case_id}")
            return []

        _raise_on_4xx_5xx(r)

        data  = r.json()
        facts = (
            data.get("data", {}).get("facts")
            or data.get("data", {}).get("case_facts")
            or data.get("facts")
            or []
        )

        if isinstance(data.get("data"), list):
            facts = data["data"]

        print(f"   get_case_facts → Found {len(facts)} facts ✅")

        for fact in facts:
            raw = fact.get("FACT_VALUE_STR")
            if raw and isinstance(raw, str):
                try:
                    fact["FACT_VALUE_PARSED"] = json.loads(raw)
                except json.JSONDecodeError:
                    fact["FACT_VALUE_PARSED"] = {}
            else:
                fact["FACT_VALUE_PARSED"] = {}

        return facts

    def create_facts(self, payload: dict) -> dict:
        log.info("tools_client.create_facts", case_id=payload.get("case_id"))
        return {"created": True}

    def create_fact(self, payload: dict) -> dict:
        log.info("tools_client.create_fact")
        return {"created": True}

    # ══════════════════════════════════════════════════════════════════
    # ERROR LOGGING
    # ══════════════════════════════════════════════════════════════════

    def log_error(
        self,
        case_id         : int         = 0,
        task_id         : int | None  = None,
        error_detail    : str         = "",
        node_name       : str         = "",
        node_key        : str | None  = None,
        handler_key     : str | None  = None,
        error_message   : str | None  = None,
        error_code      : str | None  = None,
        error_source    : str | None  = None,
        error_retryable : bool        = True,
        error_json      : dict | None = None,
        suggested_action: str | None  = None,
        run_id          : str | None  = None,
        graph_name      : str | None  = None,
        graph_version   : str | None  = None,
        node_index      : int | None  = None,
        correlation_id  : str | None  = None,
    ) -> dict:
        body = {
            "task_id"         : task_id or 0,
            "node_key"        : node_key or node_name,
            "error_message"   : error_message or error_detail,
            "handler_key"     : handler_key,
            "error_code"      : error_code,
            "error_source"    : error_source,
            "error_retryable" : error_retryable,
            "error_json"      : error_json,
            "suggested_action": suggested_action,
            "run_id"          : run_id,
            "graph_name"      : graph_name,
            "graph_version"   : graph_version,
            "node_index"      : node_index,
        }
        try:
            r = self._http.post(
                "/api/v1/workflow-engine/log-error/rcm_error",
                json=body,
            )
            _raise_on_4xx_5xx(r)
            return r.json()
        except Exception as exc:
            log.warning("tools_client.log_error_failed", error=str(exc))
            return {}

    # ══════════════════════════════════════════════════════════════════
    # STEP HISTORY
    # ══════════════════════════════════════════════════════════════════

    def create_step_history(self, payload: dict) -> dict:
        body = {
            "rcm_case_id"        : payload.get("case_id"),
            "rcm_task_id"        : None,
            "run_id"             : payload.get("correlation_id"),
            "correlation_id"     : payload.get("correlation_id"),
            "node_key"           : payload.get("handler_key", "UNKNOWN"),
            "node_index"         : None,
            "started_at"         : payload.get("started_at"),
            "ended_at"           : payload.get("ended_at"),
            "duration_ms"        : None,
            "outcome_code"       : payload.get("outcome_code"),
            "output_summary_json": payload.get("output_summary_json"),
            "error_message"      : payload.get("error_detail"),
        }
        try:
            r = self._http.post(
                "/api/v1/workflow-engine/rcm_node_history",
                json=body,
            )
            _raise_on_4xx_5xx(r)
            return r.json()
        except Exception as exc:
            log.warning("tools_client.create_step_history_failed", error=str(exc))
            return {}

    # ══════════════════════════════════════════════════════════════════
    # STUBS
    # ══════════════════════════════════════════════════════════════════

    def get_patient(self, patient_id: int) -> dict | None:
        return None

    def get_patient_insurances(self, patient_id: int) -> list[dict]:
        return []

    def duplicate_check(self, patient_id: int) -> dict:
        return {"has_duplicates": False, "candidates": []}

    def has_insurance_image(self, patient_id: int, clinic_id: int | None = None) -> dict:
        return {"has_image": False}

    def deactivate_insurance(self, insurance_id: int) -> dict:
        return {"deactivated": insurance_id}

    def get_facility(self, facility_id: int) -> dict | None:
        return None

    def list_case_documents(self, case_id: int) -> list[dict]:
        return []

    def ocr_extract(self, document_id: int, mode: str = "insurance_card") -> dict:
        return {}

    def llm_parse_insurance(self, document_id: int) -> dict:
        return {}

    def verify_eligibility(self, payload: dict) -> dict:
        return {}

    def send_sms(self, phone: str, message: str, case_id: int, attempt: int) -> dict:
        return {"sent": True, "stub": True}

    def send_fax(
        self,
        fax_number   : str,
        facility_name: str,
        patient_id   : int,
        case_id      : int,
        attempt      : int,
    ) -> dict:
        return {"sent": True, "stub": True}

    def send_case_event(
        self,
        case_id       : int,
        event_type    : str,
        correlation_id: str,
        payload       : dict,
    ) -> dict:
        return {"sent": True}

    def signal_temporal(
        self,
        case_id    : int,
        signal_type: str,
        state      : dict | None = None,
    ) -> dict:
        return {"signaled": True}