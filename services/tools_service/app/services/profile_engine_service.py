"""
ProfileEngineService — determines whether this organization has direct
EMR access to a given facility.

Strategy (two-tier):
  1. Check CLINIC_MASTER for a locally-configured EMR access record
     (TYPE=50 is an example sentinel; adjust to your schema convention).
  2. Fall back to an external profile engine HTTP call (tenant-hosted service).

If neither source is available or the facility is unknown, return False
so the workflow routes to fax outreach rather than blocking.
"""
from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from shared.config import get_settings
from shared.logging import get_logger

log = get_logger(__name__)

# CLINIC_MASTER.TYPE code used to store EMR integration configuration.
# Example row: (clinic_id=83622, TYPE=50, VALUE='10', DESCRIPTION='EPIC_DIRECT')
# VALUE contains the FACILITY_ID, DESCRIPTION contains the EMR system name.
CLINIC_MASTER_TYPE_EMR_ACCESS = 50


class ProfileEngineService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._http = httpx.Client(
            base_url=self.settings.profile_engine_base_url,
            headers={"x-api-key": self.settings.profile_engine_api_key},
            timeout=15.0,
        )

    def get_emr_access(
        self,
        facility_id: int,
        clinic_id: int | None = None,
        claims_repo: Any = None,
    ) -> dict:
        """
        Returns a dict with at minimum:
          has_direct_emr_access: bool
          emr_system: str | None
          notes: str | None

        Priority order:
          1. CLINIC_MASTER local lookup (if claims_repo provided)
          2. External profile engine API
          3. Default False (fail open — route to fax)
        """
        # Step 1: Local CLINIC_MASTER lookup
        if claims_repo is not None and clinic_id is not None:
            local = self._check_clinic_master(claims_repo, clinic_id, facility_id)
            if local is not None:
                log.info(
                    "profile_engine.clinic_master_hit",
                    facility_id=facility_id,
                    clinic_id=clinic_id,
                    result=local,
                )
                return local

        # Step 2: External profile engine API
        external = self._call_profile_engine(facility_id)
        if external is not None:
            return external

        # Step 3: Safe default — no direct access, fall back to fax
        log.info(
            "profile_engine.no_access_found",
            facility_id=facility_id,
            reason="no_local_config_and_api_unavailable",
        )
        return {
            "has_direct_emr_access": False,
            "emr_system": None,
            "notes": "No EMR access record found; routing to fax outreach",
        }

    # ── Local lookup ──────────────────────────────────────────────────────────

    @staticmethod
    def _check_clinic_master(
        claims_repo: Any,
        clinic_id: int,
        facility_id: int,
    ) -> dict | None:
        """
        Look for a CLINIC_MASTER row where:
          TYPE = CLINIC_MASTER_TYPE_EMR_ACCESS (50)
          VALUE = str(facility_id)
        This represents a locally-managed list of facilities with direct EMR.
        """
        rows = claims_repo.get_clinic_config(clinic_id, CLINIC_MASTER_TYPE_EMR_ACCESS)
        for row in rows:
            try:
                if int(row.VALUE) == facility_id:
                    emr_system = row.DESCRIPTION or "DIRECT"
                    return {
                        "has_direct_emr_access": True,
                        "emr_system": emr_system,
                        "notes": f"Configured in CLINIC_MASTER for clinic {clinic_id}",
                    }
            except (TypeError, ValueError):
                continue
        return None

    # ── External profile engine ───────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
    )
    def _call_profile_engine(self, facility_id: int) -> dict | None:
        """
        Call the external profile engine API.
        Expected response:
          { "has_direct_emr_access": bool, "emr_system": str|null, "notes": str|null }
        """
        try:
            resp = self._http.get(f"/v1/facilities/{facility_id}/emr-access")
            if resp.status_code == 200:
                data = resp.json()
                log.info(
                    "profile_engine.api_hit",
                    facility_id=facility_id,
                    has_access=data.get("has_direct_emr_access"),
                )
                return {
                    "has_direct_emr_access": bool(data.get("has_direct_emr_access", False)),
                    "emr_system": data.get("emr_system"),
                    "notes": data.get("notes"),
                }
            if resp.status_code == 404:
                return {
                    "has_direct_emr_access": False,
                    "emr_system": None,
                    "notes": "Facility not found in profile engine",
                }
            log.warning(
                "profile_engine.api_unexpected_status",
                facility_id=facility_id,
                status_code=resp.status_code,
            )
            return None
        except httpx.ConnectError:
            log.warning(
                "profile_engine.api_unreachable",
                facility_id=facility_id,
                base_url=self.settings.profile_engine_base_url,
            )
            return None
