"""
ProfileEngineClient — used by LangGraph gather_registration node to check
whether we have direct EMR access to a facility.
Delegates to the Tools Service /v1/profile endpoint which in turn
checks CLINIC_MASTER and the external profile engine.
"""
from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from shared.config import get_settings
from shared.logging import get_logger

log = get_logger(__name__)


class ProfileEngineClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._http = httpx.Client(
            base_url=settings.tools_base_url,
            timeout=15.0,
            headers={"x-api-secret": settings.internal_api_secret},
        )

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(2),
        wait=wait_exponential(min=1, max=5),
    )
    def get_emr_access(
        self,
        facility_id: int,
        clinic_id: int | None = None,
    ) -> dict:
        params = {}
        if clinic_id:
            params["clinic_id"] = clinic_id
        try:
            r = self._http.get(
                f"/v1/profile/facilities/{facility_id}/emr-access",
                params=params,
            )
            if r.status_code == 200:
                return r.json()
            log.warning(
                "profile_client.unexpected_status",
                facility_id=facility_id,
                status_code=r.status_code,
            )
            return {"has_direct_emr_access": False, "emr_system": None, "notes": f"HTTP {r.status_code}"}
        except httpx.ConnectError:
            log.warning("profile_client.connect_error", facility_id=facility_id)
            return {"has_direct_emr_access": False, "emr_system": None, "notes": "Profile engine unreachable"}
