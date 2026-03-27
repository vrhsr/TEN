"""
ClaimsRepository — read-only access to allofactorv3.
All writes to the claims database go through the Tools API endpoints that
call dedicated update helpers here (update_insurance_eligibility, etc.).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, and_, or_
from sqlalchemy.orm import Session

from shared.constants import BILLING_METHOD_SELF_PAY, CLAIM_STATUS_NEW
from ..models.claims import (
    Business,
    Claim,
    ClinicMaster,
    Facility,
    Insurance,
    Patient,
    PayerInfo,
    Visit,
)


class ClaimsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Patient ──────────────────────────────────────────────────────────────

    def get_patient(self, patient_id: int) -> Patient | None:
        return self.db.get(Patient, patient_id)

    def is_self_pay(self, patient: Patient) -> bool:
        return patient.BILLING_METHOD == BILLING_METHOD_SELF_PAY

    def find_duplicate_patients(self, patient: Patient) -> list[Patient]:
        """
        Heuristic duplicate check:
          - Same CLINIC_ID + same LAST_NAME (case-insensitive) + same DOB
          - OR same SSN when SSN is non-empty and not a placeholder
          - Exclude the patient itself and deleted/inactive records.
        """
        conditions_name = and_(
            Patient.CLINIC_ID == patient.CLINIC_ID,
            func.upper(Patient.LAST_NAME) == func.upper(patient.LAST_NAME),
            Patient.DOB == patient.DOB,
            Patient.PATIENT_ID != patient.PATIENT_ID,
            Patient.MARK_AS_DELETE == 0,
            Patient.ACTIVE == 1,
        )
        results: list[Patient] = list(self.db.scalars(select(Patient).where(conditions_name)))

        if patient.SSN and patient.SSN not in ("", "000-00-0000"):
            ssn_matches = list(
                self.db.scalars(
                    select(Patient).where(
                        and_(
                            Patient.SSN == patient.SSN,
                            Patient.PATIENT_ID != patient.PATIENT_ID,
                            Patient.MARK_AS_DELETE == 0,
                        )
                    )
                )
            )
            seen = {r.PATIENT_ID for r in results}
            for p in ssn_matches:
                if p.PATIENT_ID not in seen:
                    results.append(p)

        return results

    # ── Insurance ─────────────────────────────────────────────────────────────

    def get_patient_insurances(
        self, patient_id: int, active_only: bool = True
    ) -> list[Insurance]:
        stmt = select(Insurance).where(Insurance.PATIENT_ID == patient_id)
        if active_only:
            stmt = stmt.where(Insurance.ACTIVE == 1)
        stmt = stmt.order_by(Insurance.RANKING.asc())
        return list(self.db.scalars(stmt))

    def get_insurance(self, insurance_id: int) -> Insurance | None:
        return self.db.get(Insurance, insurance_id)

    def update_insurance_eligibility(
        self,
        insurance_id: int,
        eligibility_status: int,
        eligibility_check_date: datetime | None,
        copay: str | None = None,
        coins: str | None = None,
        deductible: float | None = None,
    ) -> None:
        ins = self.db.get(Insurance, insurance_id)
        if not ins:
            return
        ins.ELIGIBILITY_STATUS = eligibility_status
        ins.ELIGIBILITY_CHECK_DATE = eligibility_check_date or datetime.utcnow().date()
        if copay is not None:
            ins.COPAY = copay
        if coins is not None:
            ins.COINS = coins
        if deductible is not None:
            ins.DEDUCTABLE = deductible
        self.db.commit()

    def deactivate_insurance(self, insurance_id: int) -> None:
        ins = self.db.get(Insurance, insurance_id)
        if ins:
            ins.ACTIVE = 0
            self.db.commit()

    def is_recently_verified(self, insurance: Insurance, freshness_days: int) -> bool:
        if not insurance.ELIGIBILITY_CHECK_DATE:
            return False
        cutoff = (datetime.utcnow() - timedelta(days=freshness_days)).date()
        check_date = (
            insurance.ELIGIBILITY_CHECK_DATE
            if isinstance(insurance.ELIGIBILITY_CHECK_DATE, datetime.__class__)
            else insurance.ELIGIBILITY_CHECK_DATE
        )
        # Handle both date and datetime objects
        try:
            return check_date >= cutoff  # type: ignore[operator]
        except TypeError:
            return False

    # ── Business / Payer ──────────────────────────────────────────────────────

    def get_business(self, business_id: int) -> Business | None:
        return self.db.get(Business, business_id)

    def get_payer_info(self, payer_info_id: int) -> PayerInfo | None:
        return self.db.get(PayerInfo, payer_info_id)

    def get_payer_info_for_insurance(
        self, insurance: Insurance
    ) -> tuple[Business | None, PayerInfo | None]:
        business = self.get_business(insurance.COMPANY_ID) if insurance.COMPANY_ID else None
        payer_info = (
            self.get_payer_info(business.PAYER_INFO_ID)
            if business and business.PAYER_INFO_ID
            else None
        )
        return business, payer_info

    # ── Facility / Clinic ─────────────────────────────────────────────────────

    def get_facility(self, facility_id: int) -> Facility | None:
        return self.db.get(Facility, facility_id)

    def get_clinic_config(self, clinic_id: int, config_type: int) -> list[ClinicMaster]:
        return list(
            self.db.scalars(
                select(ClinicMaster).where(
                    ClinicMaster.CLINIC_ID == clinic_id,
                    ClinicMaster.TYPE == config_type,
                )
            )
        )

    # ── Claims / Charges ──────────────────────────────────────────────────────

    def get_claim(self, claim_id: int) -> Claim | None:
        return self.db.get(Claim, claim_id)

    def get_visit(self, visit_id: int) -> Visit | None:
        return self.db.get(Visit, visit_id)

    def find_new_charges(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        Return new charges from the CLAIM table that have not yet been picked
        up by a demographics workflow case.
        STATUS = CLAIM_STATUS_NEW (1) = new/pending claims awaiting demographics.
        READY_TO_SENT = 0 means not yet submitted.
        MARK_AS_DELETE = 0 is a soft-delete guard.
        """
        stmt = (
            select(Claim)
            .where(
                Claim.STATUS == CLAIM_STATUS_NEW,
                Claim.READY_TO_SENT == 0,
                Claim.MARK_AS_DELETE == 0,
            )
            .order_by(Claim.DT_CREATED_DATE.asc())
            .limit(limit)
        )
        claims = list(self.db.scalars(stmt))
        return [
            {
                "claim_id": c.CLAIM_ID,
                "clinic_id": c.CLINIC_ID,
                "patient_id": c.PATIENT_ID,
                "provider_id": c.PROVIDER_ID,
                "visit_id": c.VISIT_ID,
                "facility_id": c.FACILITY_ID,
                "charge_id": c.CLAIM_ID,   # charge_id = claim_id in this schema
                "dos": str(c.DOS) if c.DOS else None,
                "billing_method": c.BILLING_METHOD,
                "primary_payer_id": c.PRIMARY_PAYER_ID,
                "primary_insurance_id": c.PRIMARY_INSURANCE_ID,
            }
            for c in claims
        ]

    def update_claim_status(self, claim_id: int, status: int) -> None:
        claim = self.db.get(Claim, claim_id)
        if claim:
            claim.STATUS = status
            self.db.commit()

    # ── Insurance card / image lookups ────────────────────────────────────────

    def has_insurance_image_in_claims(self, patient_id: int, clinic_id: int) -> bool:
        """
        Checks whether the claims system already has an insurance image or
        facesheet stored.  In allofactorv3 this is indicated by FOLDER_ID > 0
        on any active INSURANCE row, which means a scanned document was linked.
        Adjust this sentinel to match your tenant's document workflow.
        """
        stmt = select(Insurance).where(
            Insurance.PATIENT_ID == patient_id,
            Insurance.CLINIC_ID == clinic_id,
            Insurance.ACTIVE == 1,
            Insurance.FOLDER_ID > 0,
        )
        return self.db.scalars(stmt).first() is not None

    # ── Medicare / Medicare Advantage detection ───────────────────────────────

    def has_medicare_advantage_conflict(self, insurances: list[Insurance]) -> bool:
        """
        Returns True when both a standard Medicare policy and a Medicare
        Advantage policy exist and are active.  PAYER_NAME patterns are a
        best-effort approach; production systems should use PAYER_INFO lookups.
        """
        names = [(i.PAYER_NAME or "").lower() for i in insurances if i.ACTIVE]
        has_medicare = any("medicare" in n and "advantage" not in n for n in names)
        has_advantage = any("advantage" in n or "ma " in n for n in names)
        return has_medicare and has_advantage
