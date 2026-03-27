"""
Read-only SQLAlchemy models mapped to the allofactorv3 claims database.
Column names use UPPER_CASE to match the existing schema exactly.
All writes to claims tables must go through the Tools API, never directly.
"""
from sqlalchemy import Date, DateTime, Double, Integer, SmallInteger, String, Text, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import ClaimsBase


class Patient(ClaimsBase):
    __tablename__ = "PATIENT"

    PATIENT_ID: Mapped[int] = mapped_column(Integer, primary_key=True)
    CLINIC_ID: Mapped[int | None] = mapped_column(Integer)
    GUARANTOR_ID: Mapped[int | None] = mapped_column(Integer)
    MRN: Mapped[str | None] = mapped_column(String(15))
    FIRST_NAME: Mapped[str | None] = mapped_column(String(35))
    LAST_NAME: Mapped[str | None] = mapped_column(String(35))
    MIDDLE_NAME: Mapped[str | None] = mapped_column(String(35))
    SSN: Mapped[str | None] = mapped_column(String(11))
    DOB: Mapped[object | None] = mapped_column(DateTime)
    SEX: Mapped[int | None] = mapped_column(SmallInteger)
    MARITAL_STATUS: Mapped[int | None] = mapped_column(SmallInteger)
    ADDRESS_LINE1: Mapped[str | None] = mapped_column(String(35))
    ADDRESS_LINE2: Mapped[str | None] = mapped_column(String(35))
    CITY: Mapped[str | None] = mapped_column(String(35))
    STATE: Mapped[str | None] = mapped_column(String(2))
    ZIP: Mapped[str | None] = mapped_column(String(10))
    PHONE: Mapped[str | None] = mapped_column(String(20))
    ALT_PHONE: Mapped[str | None] = mapped_column(String(14))
    MOBILE: Mapped[str | None] = mapped_column(String(14))
    EMAIL: Mapped[str | None] = mapped_column(String(50))
    BILLING_METHOD: Mapped[int | None] = mapped_column(SmallInteger)  # 0 = self-pay
    ACTIVE: Mapped[int | None] = mapped_column(SmallInteger)
    IS_DECEASED: Mapped[int | None] = mapped_column(SmallInteger)
    FACILITY_ID: Mapped[int | None] = mapped_column(Integer)
    PROVIDER_ID: Mapped[int | None] = mapped_column(Integer)
    ACCOUNT_STATUS: Mapped[int | None] = mapped_column(SmallInteger)
    DT_CREATED_DATE: Mapped[object | None] = mapped_column(DateTime)
    MARK_AS_DELETE: Mapped[int | None] = mapped_column(SmallInteger)


class Insurance(ClaimsBase):
    __tablename__ = "INSURANCE"

    INSURANCE_ID: Mapped[int] = mapped_column(Integer, primary_key=True)
    CLINIC_ID: Mapped[int | None] = mapped_column(Integer)
    PATIENT_ID: Mapped[int | None] = mapped_column(Integer)
    POLICY_HOLDER_ID: Mapped[int | None] = mapped_column(Integer)
    COMPANY_ID: Mapped[int | None] = mapped_column(Integer)       # FK → BUSINESS.BUSINESS_ID
    FOLDER_ID: Mapped[int | None] = mapped_column(Integer)
    ELIGIBILITY_ID: Mapped[int | None] = mapped_column(Integer)
    INSURANCE_TYPE: Mapped[int | None] = mapped_column(SmallInteger)
    RANKING: Mapped[int | None] = mapped_column(SmallInteger)      # 1 = primary, 2 = secondary
    POLICY_NO: Mapped[str | None] = mapped_column(String(20))
    GROUP_NO: Mapped[str | None] = mapped_column(String(20))
    EDOC_START: Mapped[object | None] = mapped_column(Date)
    EDOC_END: Mapped[object | None] = mapped_column(Date)
    ELIGIBILITY_STATUS: Mapped[int | None] = mapped_column(SmallInteger)
    PAYER_NAME: Mapped[str | None] = mapped_column(String(200))
    POLICY_HOLDER_F_NAME: Mapped[str | None] = mapped_column(String(35))
    POLICY_HOLDER_L_NAME: Mapped[str | None] = mapped_column(String(35))
    POLICY_HOLDER_M_NAME: Mapped[str | None] = mapped_column(String(35))
    ACTIVE: Mapped[int | None] = mapped_column(SmallInteger)        # 1 = active
    BUSINESS_ADDRESS_ID: Mapped[int | None] = mapped_column(Integer)
    COPAY: Mapped[str | None] = mapped_column(String(20))
    COINS: Mapped[str | None] = mapped_column(String(20))
    DEDUCTABLE: Mapped[float | None] = mapped_column(Double)
    ELIGIBILITY_CHECK_DATE: Mapped[object | None] = mapped_column(Date)
    STATUS: Mapped[int | None] = mapped_column(SmallInteger)


class Business(ClaimsBase):
    """Payer / insurance company master — maps to PAYER_INFO via PAYER_INFO_ID."""
    __tablename__ = "BUSINESS"

    BUSINESS_ID: Mapped[int] = mapped_column(Integer, primary_key=True)
    CLINIC_ID: Mapped[int | None] = mapped_column(Integer)
    PAYER_INFO_ID: Mapped[int | None] = mapped_column(Integer)      # FK → PAYER_INFO.PAYER_INFO_ID
    BUSINESS_TYPE: Mapped[int | None] = mapped_column(SmallInteger)
    NAME: Mapped[str | None] = mapped_column(String(200))
    NAME_ALIAS: Mapped[str | None] = mapped_column(String(200))
    INSURANCE_TYPE: Mapped[int | None] = mapped_column(SmallInteger)
    FILING_MODE: Mapped[int | None] = mapped_column(SmallInteger)
    CLEARING_HOUSE_TYPE: Mapped[int | None] = mapped_column(SmallInteger)
    ELG_CLHOUSE_TYPE: Mapped[int | None] = mapped_column(SmallInteger)
    PAYER_NO: Mapped[str | None] = mapped_column(String(25))
    CLEARING_HOUSE_PAYER: Mapped[str | None] = mapped_column(String(100))
    ACTIVE: Mapped[int | None] = mapped_column(SmallInteger)
    MARK_AS_DELETE: Mapped[int | None] = mapped_column(SmallInteger)


class PayerInfo(ClaimsBase):
    """Clearinghouse payer identifier table — linked from BUSINESS.PAYER_INFO_ID."""
    __tablename__ = "PAYER_INFO"

    PAYER_INFO_ID: Mapped[int] = mapped_column(Integer, primary_key=True)
    ELG_PAYER_INFO_ID: Mapped[int | None] = mapped_column(Integer)
    ZIRMED_PAYER_NO: Mapped[str | None] = mapped_column(String(20))
    OFFALLY_PAYER_NO: Mapped[str | None] = mapped_column(String(20))
    AVAILITY_PAYER_NO: Mapped[str | None] = mapped_column(String(20))
    ZIRMED_ELG_CODE: Mapped[str | None] = mapped_column(String(5))
    OFFICEALLY_ELG_CODE: Mapped[str | None] = mapped_column(String(20))
    PAYER_TYPE: Mapped[str | None] = mapped_column(String(20))
    PAYER_NAME: Mapped[str | None] = mapped_column(String(100))
    PAYER_ALIAS: Mapped[str | None] = mapped_column(String(100))
    CLM_CLEARINGHOUSE: Mapped[int | None] = mapped_column(SmallInteger)
    ELG_CLEARINGHOUSE: Mapped[int | None] = mapped_column(SmallInteger)
    ERA_CLEARINGHOUSE: Mapped[int | None] = mapped_column(SmallInteger)
    CLM_ENROLLMENT: Mapped[int | None] = mapped_column(SmallInteger)
    ELG_ENROLLMENT: Mapped[int | None] = mapped_column(SmallInteger)
    ERA_ENROLLMENT: Mapped[int | None] = mapped_column(SmallInteger)
    STATUS: Mapped[int | None] = mapped_column(SmallInteger)
    MARK_AS_DELETE: Mapped[int | None] = mapped_column(SmallInteger)
    TIMELY_FILING_LIMIT: Mapped[int | None] = mapped_column(Integer)
    GATEWAY_PAYER_NO: Mapped[str | None] = mapped_column(String(20))


class Facility(ClaimsBase):
    __tablename__ = "FACILITY"

    FACILITY_ID: Mapped[int] = mapped_column(Integer, primary_key=True)
    CLINIC_ID: Mapped[int | None] = mapped_column(Integer)
    TYPE: Mapped[int | None] = mapped_column(SmallInteger)
    FACILITY_NAME: Mapped[str | None] = mapped_column(String(50))
    ADDRESS_LINE1: Mapped[str | None] = mapped_column(String(35))
    ADDRESS_LINE2: Mapped[str | None] = mapped_column(String(35))
    CITY: Mapped[str | None] = mapped_column(String(35))
    STATE: Mapped[str | None] = mapped_column(String(2))
    ZIP: Mapped[str | None] = mapped_column(String(10))
    PHONE: Mapped[str | None] = mapped_column(String(20))
    FAX: Mapped[str | None] = mapped_column(String(14))
    NPI: Mapped[str | None] = mapped_column(String(10))
    POS: Mapped[str | None] = mapped_column(String(3))
    IS_DEFAULT: Mapped[int | None] = mapped_column(SmallInteger)
    MARK_AS_DELETE: Mapped[int | None] = mapped_column(SmallInteger)
    DISABLED: Mapped[int | None] = mapped_column(SmallInteger)


class ClinicMaster(ClaimsBase):
    """
    Clinic configuration key-value store.
    TYPE codes relevant to demographics agent:
      - TYPE=22 → denial/correction reason codes (used for workflow routing notes)
      - Other types are clinic-specific configuration.
    """
    __tablename__ = "CLINIC_MASTER"

    CLINIC_MASTER_ID: Mapped[int] = mapped_column(Integer, primary_key=True)
    CLINIC_ID: Mapped[int | None] = mapped_column(Integer)
    TYPE: Mapped[int | None] = mapped_column(SmallInteger)
    VALUE: Mapped[str | None] = mapped_column(String(35))
    DESCRIPTION: Mapped[str | None] = mapped_column(String(500))


class Claim(ClaimsBase):
    __tablename__ = "CLAIM"

    CLAIM_ID: Mapped[int] = mapped_column(Integer, primary_key=True)
    CLINIC_ID: Mapped[int | None] = mapped_column(Integer)
    PATIENT_ID: Mapped[int | None] = mapped_column(Integer)
    PROVIDER_ID: Mapped[int | None] = mapped_column(Integer)
    VISIT_ID: Mapped[int | None] = mapped_column(Integer)
    PRIMARY_PAYER_ID: Mapped[int | None] = mapped_column(Integer)
    SECONDARY_PAYER_ID: Mapped[int | None] = mapped_column(Integer)
    PRIMARY_INSURANCE_ID: Mapped[int | None] = mapped_column(Integer)
    SECONDARY_INSURANCE_ID: Mapped[int | None] = mapped_column(Integer)
    FACILITY_ID: Mapped[int | None] = mapped_column(Integer)
    DOS: Mapped[object | None] = mapped_column(Date)
    PATIENT_NAME: Mapped[str | None] = mapped_column(String(110))
    MRN: Mapped[str | None] = mapped_column(String(15))
    PROVIDER_NAME: Mapped[str | None] = mapped_column(String(130))
    PRIMARY_PAYER_NAME: Mapped[str | None] = mapped_column(String(100))
    BILLING_METHOD: Mapped[int | None] = mapped_column(SmallInteger)
    STATUS: Mapped[int | None] = mapped_column(SmallInteger)   # 1 = new
    FILING_MODE: Mapped[int | None] = mapped_column(SmallInteger)
    READY_TO_SENT: Mapped[int | None] = mapped_column(SmallInteger)
    DT_CREATED_DATE: Mapped[object | None] = mapped_column(DateTime)
    MARK_AS_DELETE: Mapped[int | None] = mapped_column(SmallInteger)


class Visit(ClaimsBase):
    __tablename__ = "VISIT"

    VISIT_ID: Mapped[int] = mapped_column(Integer, primary_key=True)
    CLINIC_ID: Mapped[int | None] = mapped_column(Integer)
    PATIENT_ID: Mapped[int | None] = mapped_column(Integer)
    PROVIDER_ID: Mapped[int | None] = mapped_column(Integer)
    FACILITY_ID: Mapped[int | None] = mapped_column(Integer)
    DOS: Mapped[object | None] = mapped_column(Date)
    POS: Mapped[str | None] = mapped_column(String(3))
    VISIT_TYPE: Mapped[int | None] = mapped_column(SmallInteger)
    STATUS: Mapped[int | None] = mapped_column(SmallInteger)
    DT_CREATED_DATE: Mapped[object | None] = mapped_column(DateTime)
    MARK_AS_DELETE: Mapped[int | None] = mapped_column(SmallInteger)
