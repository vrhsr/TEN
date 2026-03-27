import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from shared.config import get_settings
from shared.logging import get_logger

log = get_logger(__name__)


class ToolsClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._http = httpx.Client(
            base_url=settings.tools_base_url,
            timeout=30.0,
            headers={"x-api-secret": settings.internal_api_secret},
        )

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def get_new_charges(self, limit: int) -> list[dict]:
        r = self._http.get("/v1/claims/charges/new", params={"limit": limit})
        r.raise_for_status()
        return r.json()

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def create_case(self, payload: dict) -> dict:
        r = self._http.post("/v1/rcm/cases", json=payload)
        r.raise_for_status()
        return r.json()

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def list_cases_due(self, limit: int = 200) -> list[dict]:
        r = self._http.get("/v1/rcm/cases/due/list", params={"limit": limit})
        r.raise_for_status()
        return r.json()


class OrchestrationClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._http = httpx.Client(
            base_url=settings.orchestration_base_url,
            timeout=60.0,
            headers={"x-api-secret": settings.internal_api_secret},
        )

    @retry(retry=retry_if_exception_type(httpx.TransportError), stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=15))
    def advance_case(self, case_id: int, correlation_id: str) -> dict:
        payload = {
            "case_id": case_id,
            "trigger": {"type": "TIMER", "correlation_id": correlation_id},
        }
        r = self._http.post("/v1/cases/advance", json=payload)
        if r.status_code >= 500:
            r.raise_for_status()
        return r.json()
