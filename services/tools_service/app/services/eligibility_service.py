"""
EligibilityService — wraps the Availity real-time eligibility API (270/271).

OAuth2 client-credentials token is cached in-process and refreshed on expiry.
The normalizer converts Availity's 271 JSON into the canonical fields stored
in RcmEligibilityResult.

Reference: https://developer.availity.com/partner/reference/eligibility
"""
from __future__ import annotations

import time
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from shared.config import get_settings
from shared.constants import CLEARINGHOUSE_AVAILITY
from shared.logging import get_logger

log = get_logger(__name__)


class AvailityTokenCache:
    """Thread-unsafe single-process token cache; replace with Redis for multi-process."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0

    def is_valid(self) -> bool:
        return self._token is not None and time.time() < self._expires_at - 30

    def set(self, token: str, expires_in: int) -> None:
        self._token = token
        self._expires_at = time.time() + expires_in

    @property
    def token(self) -> str | None:
        return self._token


_token_cache = AvailityTokenCache()


class EligibilityService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.availity_base_url
        self.client_id = self.settings.availity_client_id
        self.client_secret = self.settings.availity_client_secret
        self.http = httpx.Client(timeout=30.0)

    # ── Public API ────────────────────────────────────────────────────────────

    def verify(self, payload: dict) -> dict:
        """
        Run an eligibility verification.

        payload keys (from EligibilityVerifyRequest):
          case_id, patient_id, insurance_id, clearinghouse,
          payer_info_id, payer_number, request_payload

        Returns a normalized eligibility result dict.
        """
        if not self.client_id or not self.client_secret:
            log.warning("eligibility.availity_credentials_not_configured")
            return self._not_configured_result(payload)

        payer_number = payload.get("payer_number") or ""
        if not payer_number:
            return self._error_result(payload, "NO_PAYER_NUMBER", "Availity payer number not available")

        token = self._get_token()
        return self._call_availity(token, payload, payer_number)

    def can_verify_electronically(self, insurance_type: int | None, payer_number: str | None) -> bool:
        """
        Returns True when this insurance policy can be verified electronically.
        Insurance types 9 = workers comp / auto / PI — must go manual.
        INSURANCE_TYPE=9 in allofactorv3 = other/not-mapped.
        """
        if not payer_number:
            return False
        # INSURANCE_TYPE tinyint codes from allofactorv3 INSURANCE table:
        # 0=unknown, 1=commercial, 2=medicare, 3=medicaid, 4=tricare,
        # 5=champus, 6=feca, 7=other federal, 8=title, 9=other (WC/auto/PI)
        manual_types = {9}
        return insurance_type not in manual_types

    # ── OAuth2 token ──────────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    def _get_token(self) -> str:
        if _token_cache.is_valid():
            return _token_cache.token  # type: ignore[return-value]

        log.info("eligibility.availity.token_refresh")
        resp = self.http.post(
            f"{self.base_url}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "hipaa",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        body = resp.json()
        _token_cache.set(body["access_token"], int(body.get("expires_in", 3600)))
        return _token_cache.token  # type: ignore[return-value]

    # ── Availity 270 call ─────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
    )
    def _call_availity(self, token: str, payload: dict, payer_number: str) -> dict:
        req_body = payload.get("request_payload") or {}
        request_json = {
            "payerId": payer_number,
            "providerNpi": req_body.get("provider_npi", ""),
            "memberId": req_body.get("member_id") or payload.get("policy_no", ""),
            "groupNumber": req_body.get("group_no", ""),
            "firstName": req_body.get("subscriber_first_name", ""),
            "lastName": req_body.get("subscriber_last_name", ""),
            "birthDate": req_body.get("subscriber_dob", ""),
            "serviceTypeCode": req_body.get("service_type_code", "30"),  # 30 = health benefit plan
        }

        log.info(
            "eligibility.availity.request",
            case_id=payload.get("case_id"),
            insurance_id=payload.get("insurance_id"),
            payer_number=payer_number,
        )

        resp = self.http.post(
            f"{self.base_url}/eligibility-and-benefits/270",
            json=request_json,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

        if resp.status_code == 200:
            raw = resp.json()
            normalized = self._normalize_271(raw)
            normalized["raw_request_json"] = request_json
            normalized["raw_response_json"] = raw
            normalized["clearinghouse_name"] = CLEARINGHOUSE_AVAILITY
            normalized["payer_number"] = payer_number
            log.info(
                "eligibility.availity.response",
                coverage_status=normalized.get("coverage_status"),
                case_id=payload.get("case_id"),
            )
            return normalized
        else:
            log.error(
                "eligibility.availity.http_error",
                status_code=resp.status_code,
                body=resp.text[:500],
            )
            return self._error_result(
                payload,
                f"HTTP_{resp.status_code}",
                f"Availity returned {resp.status_code}",
                raw_request=request_json,
                raw_response={"status_code": resp.status_code, "body": resp.text[:2000]},
            )

    # ── 271 response normalizer ───────────────────────────────────────────────

    @staticmethod
    def _normalize_271(raw: dict) -> dict:
        """
        Map Availity 271 response fields to our canonical eligibility schema.
        The exact path depends on the Availity API version; adjust field paths
        per your tenant's API contract version.
        """
        # Availity wraps the 271 under `eligibilityBenefits` or top-level
        benefits = raw.get("eligibilityBenefits") or raw.get("benefits") or []
        subscriber = raw.get("subscriber") or raw.get("member") or {}
        coverage_status = raw.get("coverageStatus") or raw.get("status") or "UNKNOWN"

        def _find_benefit(benefit_type_code: str) -> dict:
            for b in benefits:
                if b.get("benefitTypeCode") == benefit_type_code or b.get("type") == benefit_type_code:
                    return b
            return {}

        def _money(b: dict) -> float | None:
            amt = b.get("benefitAmount") or b.get("amount")
            try:
                return float(amt) if amt is not None else None
            except (TypeError, ValueError):
                return None

        # Benefit type codes (X12 271): C = copay, A = deductible, G = OOP, B = coinsurance
        copay_b = _find_benefit("C")
        deduct_b = _find_benefit("A")
        oop_b = _find_benefit("G")
        coins_b = _find_benefit("B")

        plan_dates = raw.get("planDateInformation") or {}

        return {
            "coverage_status": coverage_status.upper() if coverage_status else "UNKNOWN",
            "copay_amount": _money(copay_b),
            "coinsurance_percent": _money(coins_b),
            "deductible_amount": _money(deduct_b),
            "deductible_remaining_amount": None,  # requires in-network deductible remaining
            "family_deductible_amount": None,
            "family_deductible_remaining_amount": None,
            "out_of_pocket_amount": _money(oop_b),
            "out_of_pocket_remaining": None,
            "plan_begin_date": plan_dates.get("planBegin") or plan_dates.get("beginDate"),
            "plan_end_date": plan_dates.get("planEnd") or plan_dates.get("endDate"),
            "subscriber_first_name": subscriber.get("firstName"),
            "subscriber_last_name": subscriber.get("lastName"),
            "subscriber_dob": subscriber.get("birthDate"),
            "result_code": "ACTIVE" if str(coverage_status).upper() in ("ACTIVE", "1", "Y") else "INACTIVE",
            "result_note": raw.get("rejectReason") or raw.get("additionalInformation"),
            "normalized_json": raw,
        }

    # ── Error / stub helpers ──────────────────────────────────────────────────

    @staticmethod
    def _error_result(
        payload: dict,
        code: str,
        note: str,
        raw_request: dict | None = None,
        raw_response: dict | None = None,
    ) -> dict:
        return {
            "coverage_status": "UNKNOWN",
            "result_code": code,
            "result_note": note,
            "clearinghouse_name": CLEARINGHOUSE_AVAILITY,
            "raw_request_json": raw_request,
            "raw_response_json": raw_response,
            "normalized_json": None,
        }

    @staticmethod
    def _not_configured_result(payload: dict) -> dict:
        return {
            "coverage_status": "UNKNOWN",
            "result_code": "NOT_CONFIGURED",
            "result_note": "Availity credentials not configured",
            "clearinghouse_name": CLEARINGHOUSE_AVAILITY,
            "raw_request_json": None,
            "raw_response_json": None,
            "normalized_json": None,
        }
