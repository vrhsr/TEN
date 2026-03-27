"""
ToolsClient — used by LangGraph nodes to call the Tools Service API.
All calls are synchronous HTTP with tenacity retry on transient failures.
"""
from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

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
        settings = get_settings()
        self._base_url = settings.tools_base_url
        self._secret = settings.internal_api_secret
        self._http = httpx.Client(
            base_url=self._base_url,
            timeout=30.0,
            headers={
                "Content-Type": "application/json",
                "x-api-secret": self._secret,
            },
        )

    # ── Cases ─────────────────────────────────────────────────────────────────

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def get_case(self, case_id: int) -> dict:
        r = self._http.get(f"/v1/rcm/cases/{case_id}/full")
        _raise_on_4xx_5xx(r)
        return r.json()

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def update_case(self, case_id: int, payload: dict) -> dict:
        r = self._http.patch(f"/v1/rcm/cases/{case_id}", json=payload)
        _raise_on_4xx_5xx(r)
        return r.json()

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def send_case_event(self, case_id: int, event_type: str, correlation_id: str, payload: dict) -> dict:
        from datetime import datetime, timezone
        r = self._http.post(f"/v1/rcm/cases/{case_id}/events", json={
            "event_type": event_type,
            "event_time": datetime.now(timezone.utc).isoformat(),
            "correlation_id": correlation_id,
            "payload": payload,
        })
        _raise_on_4xx_5xx(r)
        return r.json()

    # ── Tasks ─────────────────────────────────────────────────────────────────

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def get_task(self, task_id: int) -> dict:
        r = self._http.get(f"/v1/rcm/tasks/{task_id}")
        _raise_on_4xx_5xx(r)
        return r.json()

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def create_task(self, payload: dict) -> dict:
        r = self._http.post("/v1/rcm/tasks", json=payload)
        _raise_on_4xx_5xx(r)
        return r.json()

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def update_task(self, task_id: int, payload: dict) -> dict:
        r = self._http.patch(f"/v1/rcm/tasks/{task_id}", json=payload)
        _raise_on_4xx_5xx(r)
        return r.json()

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def signal_temporal(self, case_id: int, signal_type: str, state: dict | None = None) -> dict:
        """Send a signal to the Temporal workflow for this case."""
        r = self._http.post(f"/v1/rcm/cases/{case_id}/signal-temporal", json={
            "signal_type": signal_type,
            "state": state or {},
        })
        _raise_on_4xx_5xx(r)
        return r.json()

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
    def log_error(self, case_id: int, task_id: int | None, error_detail: str, node_name: str) -> dict:
        """Write an error entry to the RCM_ERROR table."""
        r = self._http.post("/v1/rcm/errors", json={
            "case_id": case_id,
            "task_id": task_id,
            "node_name": node_name,
            "error_detail": error_detail,
        })
        _raise_on_4xx_5xx(r)
        return r.json()


    # ── Facts ─────────────────────────────────────────────────────────────────

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def create_fact(self, payload: dict) -> dict:
        r = self._http.post("/v1/rcm/facts", json=payload)
        _raise_on_4xx_5xx(r)
        return r.json()

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def create_facts(self, payload: dict) -> dict:
        r = self._http.post("/v1/rcm/facts/bulk", json=payload)
        _raise_on_4xx_5xx(r)
        return r.json()

    # ── Step History ──────────────────────────────────────────────────────────

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def create_step_history(self, payload: dict) -> dict:
        r = self._http.post("/v1/rcm/step-history", json=payload)
        _raise_on_4xx_5xx(r)
        return r.json()

    # ── Patients ──────────────────────────────────────────────────────────────

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def get_patient(self, patient_id: int) -> dict | None:
        r = self._http.get(f"/v1/patients/{patient_id}")
        if r.status_code == 404:
            return None
        _raise_on_4xx_5xx(r)
        return r.json()

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def get_patient_insurances(self, patient_id: int) -> list[dict]:
        r = self._http.get(f"/v1/patients/{patient_id}/insurances")
        _raise_on_4xx_5xx(r)
        return r.json()

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def duplicate_check(self, patient_id: int) -> dict:
        r = self._http.post(f"/v1/patients/{patient_id}/duplicate-check")
        _raise_on_4xx_5xx(r)
        return r.json()

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def has_insurance_image(self, patient_id: int, clinic_id: int | None) -> dict:
        params = {"clinic_id": clinic_id} if clinic_id else {}
        r = self._http.get(f"/v1/patients/{patient_id}/insurance-image-check", params=params)
        _raise_on_4xx_5xx(r)
        return r.json()

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def deactivate_insurance(self, insurance_id: int) -> dict:
        # Thin wrapper — calls a claims write endpoint when implemented
        # Currently a best-effort no-op stub until write endpoints are enabled
        log.info("tools_client.deactivate_insurance", insurance_id=insurance_id)
        return {"deactivated": insurance_id}

    # ── Facilities ────────────────────────────────────────────────────────────

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def get_facility(self, facility_id: int) -> dict | None:
        r = self._http.get(f"/v1/facilities/{facility_id}")
        if r.status_code == 404:
            return None
        _raise_on_4xx_5xx(r)
        return r.json()

    # ── Documents ─────────────────────────────────────────────────────────────

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def list_case_documents(self, case_id: int) -> list[dict]:
        r = self._http.get(f"/v1/rcm/cases/{case_id}/documents")
        _raise_on_4xx_5xx(r)
        return r.json()

    # ── OCR / LLM ─────────────────────────────────────────────────────────────

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=10))
    def ocr_extract(self, document_id: int, mode: str = "insurance_card") -> dict:
        r = self._http.post("/v1/ocr/extract", json={"document_id": document_id, "mode": mode})
        _raise_on_4xx_5xx(r)
        return r.json()

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=10))
    def llm_parse_insurance(self, document_id: int) -> dict:
        r = self._http.post("/v1/llm/insurance-parse", params={"document_id": document_id})
        _raise_on_4xx_5xx(r)
        return r.json()

    # ── Eligibility ───────────────────────────────────────────────────────────

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=15))
    def verify_eligibility(self, payload: dict) -> dict:
        r = self._http.post("/v1/eligibility/verify", json=payload)
        _raise_on_4xx_5xx(r)
        return r.json()

    # ── Communication stubs (wire to your outreach platform) ─────────────────

    def send_sms(self, phone: str, message: str, case_id: int, attempt: int) -> dict:
        """Stub — replace with Twilio/RingCentral/etc. call."""
        log.info("tools_client.send_sms.stub", phone=phone[:4] + "****", case_id=case_id, attempt=attempt)
        return {"sent": True, "stub": True}

    def send_fax(self, fax_number: str, facility_name: str, patient_id: int, case_id: int, attempt: int) -> dict:
        """Stub — replace with eFax/RingCentral Fax API call."""
        log.info("tools_client.send_fax.stub", fax=fax_number[:4] + "****", case_id=case_id, attempt=attempt)
        return {"sent": True, "stub": True}
