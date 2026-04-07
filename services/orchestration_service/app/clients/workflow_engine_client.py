# orchestration_service/app/clients/workflow_engine_client.py
"""
WorkflowEngineClient
Calls the Tools/API layer at https://app.staging.trillium.health/temporal-rcm-workflow
All responses use UPPERCASE keys as confirmed from Swagger.
"""
from __future__ import annotations

import json
import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from shared.logging import get_logger

log = get_logger(__name__)

BASE_URL = "https://app.staging.trillium.health/temporal-rcm-workflow"


def _raise_on_error(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise httpx.HTTPStatusError(
            f"WorkflowEngine API {response.status_code}: {response.text[:300]}",
            request=response.request,
            response=response,
        )


class WorkflowEngineClient:
    def __init__(self) -> None:
        self._http = httpx.Client(
            base_url=BASE_URL,
            timeout=30.0,
            headers={"Content-Type": "application/json"},
        )

    # ══════════════════════════════════════════════════════════════════════
    # CASE
    # ══════════════════════════════════════════════════════════════════════

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def get_case_facts(self, case_id: int) -> list[dict]:
        """
        GET /api/v1/workflow-engine/{case_id}/rcm_case_fact
        Returns list of fact dicts with parsed FACT_VALUE_STR.

        Response shape:
        {
          "data": {
            "facts": [
              {
                "FACT_KEY"       : "PATIENT_FACT",
                "FACT_VALUE_STR" : "{...json string...}",
                "RCM_CASE_ID"   : 13,
                "CLINIC_ID"     : 10,
                ...
              }
            ]
          }
        }
        """
        r = self._http.get(
            f"/api/v1/workflow-engine/cases/{case_id}/facts"
        )
        _raise_on_error(r)
        facts = r.json()["data"]["facts"]

        # ── Parse FACT_VALUE_STR from JSON string to dict ──────────────────
        for fact in facts:
            raw = fact.get("FACT_VALUE_STR")
            if raw and isinstance(raw, str):
                try:
                    fact["FACT_VALUE_PARSED"] = json.loads(raw)
                except json.JSONDecodeError:
                    fact["FACT_VALUE_PARSED"] = {}
            else:
                fact["FACT_VALUE_PARSED"] = {}

        log.info(
            "workflow_engine_client.get_case_facts",
            case_id=case_id,
            fact_count=len(facts),
        )
        return facts

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def start_workflow(
        self,
        case_id: int,
        workflow_name: str,
        task_queue: str,
    ) -> dict:
        """
        POST /api/v1/workflow-engine/start
        Request: {"case_id", "workflow_name", "task_queue"}
        """
        payload = {
            "case_id"       : case_id,
            "workflow_name" : workflow_name,
            "task_queue"    : task_queue,
        }
        r = self._http.post(
            "/api/v1/workflow-engine/workflows/start",
            json=payload,
        )
        _raise_on_error(r)
        log.info(
            "workflow_engine_client.start_workflow",
            case_id=case_id,
            workflow_name=workflow_name,
        )
        return r.json()

    # ══════════════════════════════════════════════════════════════════════
    # TASK
    # ══════════════════════════════════════════════════════════════════════

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def get_task_and_case(self, task_id: int) -> dict:
        """
        GET /api/v1/workflow-engine/{task_id}/rcm_task_and_rcm_case

        Response shape:
        {
          "data": {
            "task": {
              "RCM_TASK_ID"  : 21,
              "RCM_CASE_ID"  : 13,
              "CLINIC_ID"    : 10,
              "TASK_TYPE"    : "INITIALIZE_DEMOGRAPHICS",
              "STATE_CODE"   : "WAITING",
              "QUEUE_ID"     : "INITIALIZE_DEMOGRAPHICS_QUEUE",
              "PAYLOAD_JSON" : null,
              "RESULT_JSON"  : null,
              ...
            },
            "case": {
              "RCM_CASE_ID"  : 13,
              "CLINIC_ID"    : 10,
              "PATIENT_ID"   : 492046,
              "CASE_TYPE"    : "DEMOGRAPHICS",
              "WORKFLOW_NAME": "DEMOGRAPHICS",
              "STATE_CODE"   : "DEMOGRAPHICS_CREATED",
              ...
            }
          }
        }
        """
        r = self._http.get(
            f"/api/v1/workflow-engine/tasks/{task_id}"
        )
        _raise_on_error(r)
        data = r.json()["data"]

        log.info(
            "workflow_engine_client.get_task_and_case",
            task_id=task_id,
            case_id=data["case"]["RCM_CASE_ID"],
            state_code=data["case"]["STATE_CODE"],
        )
        return data  # {"task": {...}, "case": {...}}

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
    )
    def process_task(self, task_id: int, payload: dict) -> dict:
        """
        POST /api/v1/workflow-engine/{task_id}/rcm_task/process
        Request: {"payload": {...}}

        Used AFTER node runs to store result/outcome/next_state.
        """
        r = self._http.post(
            f"/api/v1/workflow-engine/tasks/{task_id}/process",
            json={"payload": payload},
        )
        _raise_on_error(r)
        log.info(
            "workflow_engine_client.process_task",
            task_id=task_id,
            payload_keys=list(payload.keys()),
        )
        return r.json()

    # ══════════════════════════════════════════════════════════════════════
    # ERROR LOGGING
    # ══════════════════════════════════════════════════════════════════════

    def log_error(
        self,
        task_id        : int,
        node_key       : str,
        error_message  : str,
        handler_key    : str | None = None,
        error_code     : str | None = None,
        error_source   : str | None = None,
        error_retryable: bool = True,
        error_json     : dict | None = None,
        suggested_action: str | None = None,
        run_id         : str | None = None,
        graph_name     : str | None = None,
        graph_version  : str | None = None,
        node_index     : int | None = None,
    ) -> dict:
        """
        POST /api/v1/workflow-engine/log-error/rcm_error

        Request shape:
        {
          "task_id"          : int,
          "node_key"         : str,
          "error_message"    : str,
          "handler_key"      : str | null,
          "error_code"       : str | null,
          "error_source"     : str | null,
          "error_retryable"  : bool | null,
          "error_json"       : object | null,
          "suggested_action" : str | null,
          "run_id"           : str | null,
          "graph_name"       : str | null,
          "graph_version"    : str | null,
          "node_index"       : int | null
        }
        """
        body = {
            "task_id"          : task_id,
            "node_key"         : node_key,
            "error_message"    : error_message,
            "handler_key"      : handler_key,
            "error_code"       : error_code,
            "error_source"     : error_source,
            "error_retryable"  : error_retryable,
            "error_json"       : error_json,
            "suggested_action" : suggested_action,
            "run_id"           : run_id,
            "graph_name"       : graph_name,
            "graph_version"    : graph_version,
            "node_index"       : node_index,
        }
        try:
            r = self._http.post(
                "/api/v1/workflow-engine/errors",
                json=body,
            )
            _raise_on_error(r)
            log.info(
                "workflow_engine_client.log_error",
                task_id=task_id,
                node_key=node_key,
                error_message=error_message[:100],
            )
            return r.json()
        except Exception as exc:
            # Never let error logging crash the main flow
            log.warning(
                "workflow_engine_client.log_error_failed",
                task_id=task_id,
                error=str(exc),
            )
            return {}

    # ══════════════════════════════════════════════════════════════════════
    # NODE HISTORY
    # ══════════════════════════════════════════════════════════════════════

    def insert_node_history(
        self,
        rcm_case_id       : int,
        node_key          : str,
        rcm_task_id       : int | None = None,
        run_id            : str | None = None,
        correlation_id    : str | None = None,
        node_index        : int | None = None,
        started_at        : str | None = None,
        ended_at          : str | None = None,
        duration_ms       : int | None = None,
        outcome_code      : str | None = None,
        output_summary_json: dict | None = None,
        error_message     : str | None = None,
    ) -> dict:
        """
        POST /api/v1/workflow-engine/rcm_node_history

        Request shape:
        {
          "rcm_case_id"         : int,
          "rcm_task_id"         : int | null,
          "run_id"              : str | null,
          "correlation_id"      : str | null,
          "node_key"            : str,
          "node_index"          : int | null,
          "started_at"          : str | null,
          "ended_at"            : str | null,
          "duration_ms"         : int | null,
          "outcome_code"        : str | null,
          "output_summary_json" : object | null,
          "error_message"       : str | null
        }
        """
        body = {
            "rcm_case_id"         : rcm_case_id,
            "rcm_task_id"         : rcm_task_id,
            "run_id"              : run_id,
            "correlation_id"      : correlation_id,
            "node_key"            : node_key,
            "node_index"          : node_index,
            "started_at"          : started_at,
            "ended_at"            : ended_at,
            "duration_ms"         : duration_ms,
            "outcome_code"        : outcome_code,
            "output_summary_json" : output_summary_json,
            "error_message"       : error_message,
        }
        try:
            r = self._http.post(
                "/api/v1/workflow-engine/node-history",
                json=body,
            )
            _raise_on_error(r)
            log.info(
                "workflow_engine_client.insert_node_history",
                rcm_case_id=rcm_case_id,
                node_key=node_key,
                outcome_code=outcome_code,
            )
            return r.json()
        except Exception as exc:
            # Never let history logging crash the main flow
            log.warning(
                "workflow_engine_client.node_history_failed",
                rcm_case_id=rcm_case_id,
                error=str(exc),
            )
            return {}