from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, Integer, JSON,
    Numeric, String, Text, UniqueConstraint, func, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..db.base import WorkflowBase


class RcmCase(WorkflowBase):
    __tablename__ = "RCM_CASE"
    __table_args__ = (
        Index("ix_rcm_case_patient_id", "PATIENT_ID"),
        Index("ix_rcm_case_state_code", "STATE_CODE"),
        Index("ix_rcm_case_claim_id", "CLAIM_ID"),
    )

    case_id: Mapped[int] = mapped_column("RCM_CASE_ID", BigInteger, primary_key=True, autoincrement=True)
    clinic_id: Mapped[int | None] = mapped_column("CLINIC_ID", BigInteger)
    patient_id: Mapped[int | None] = mapped_column("PATIENT_ID", BigInteger)
    case_type: Mapped[str] = mapped_column("CASE_TYPE", String(64), nullable=False)
    workflow_name: Mapped[str] = mapped_column("WORKFLOW_NAME", String(64), nullable=False)
    workflow_version: Mapped[str] = mapped_column("WORKFLOW_VERSION", String(32), nullable=False, default="v1")
    claim_id: Mapped[int | None] = mapped_column("CLAIM_ID", BigInteger)
    facility_id: Mapped[int | None] = mapped_column("FACILITY_ID", BigInteger)
    provider_id: Mapped[int | None] = mapped_column("PROVIDER_ID", BigInteger)
    payer_id: Mapped[int | None] = mapped_column("PAYER_ID", BigInteger)
    state_code: Mapped[str] = mapped_column("STATE_CODE", String(64), nullable=False)
    substate_code: Mapped[str | None] = mapped_column("SUBSTATE_CODE", String(64))
    queue_id: Mapped[str | None] = mapped_column("QUEUE_ID", String(64))
    current_task_id: Mapped[int | None] = mapped_column("CURRENT_TASK_ID", BigInteger)
    due_at: Mapped[object | None] = mapped_column("DUE_AT", DateTime)
    created_at: Mapped[object] = mapped_column("CREATED_AT", DateTime, server_default=func.now())
    updated_at: Mapped[object] = mapped_column("UPDATED_AT", DateTime, server_default=func.now(), onupdate=func.now())

    # Shims for missing columns
    @property
    def context_json(self) -> dict: return {}
    @context_json.setter
    def context_json(self, value): pass

    @property
    def visit_id(self) -> int | None: return None
    @visit_id.setter
    def visit_id(self, value): pass

    @property
    def charge_id(self) -> int | None: return None
    @charge_id.setter
    def charge_id(self, value): pass

    @property
    def step_code(self) -> str | None: return None
    @step_code.setter
    def step_code(self, value): pass

    @property
    def terminal_outcome_code(self) -> str | None: return None
    @terminal_outcome_code.setter
    def terminal_outcome_code(self, value): pass

    @property
    def closed_at(self) -> object | None: return None
    @closed_at.setter
    def closed_at(self, value): pass

    @property
    def next_action_at(self) -> object | None: return None
    @next_action_at.setter
    def next_action_at(self, value): pass

    tasks: Mapped[list["RcmTask"]] = relationship("RcmTask", back_populates="case")


class RcmTask(WorkflowBase):
    __tablename__ = "RCM_TASK"
    __table_args__ = (
        Index("ix_rcm_task_queue_state", "QUEUE_ID", "STATE_CODE"),
        Index("ix_rcm_task_case_state", "RCM_CASE_ID", "STATE_CODE"),
    )

    task_id: Mapped[int] = mapped_column("RCM_TASK_ID", BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column("RCM_CASE_ID", BigInteger, ForeignKey("RCM_CASE.RCM_CASE_ID"), nullable=False)
    task_type: Mapped[str] = mapped_column("TASK_TYPE", String(64), nullable=False)
    state_code: Mapped[str] = mapped_column("STATE_CODE", String(32), nullable=False)
    priority_code: Mapped[str] = mapped_column("PRIORITY_CODE", String(32), nullable=False, default="normal")
    queue_id: Mapped[str | None] = mapped_column("QUEUE_ID", String(64))
    handler_key: Mapped[str | None] = mapped_column("HANDLER_KEY", String(128))
    attempt_count: Mapped[int] = mapped_column("ATTEMPT_COUNT", Integer, default=0)
    due_at: Mapped[object | None] = mapped_column("DUE_AT", DateTime)
    next_action_at: Mapped[object | None] = mapped_column("NEXT_ACTION_AT", DateTime)
    payload_json: Mapped[dict | None] = mapped_column("PAYLOAD_JSON", JSON)
    result_json: Mapped[dict | None] = mapped_column("RESULT_JSON", JSON)
    created_at: Mapped[object] = mapped_column("CREATED_AT", DateTime, server_default=func.now())
    updated_at: Mapped[object] = mapped_column("UPDATED_AT", DateTime, server_default=func.now(), onupdate=func.now())

    # Map intent_key to OUTCOME column
    intent_key: Mapped[str | None] = mapped_column("OUTCOME", String(255), nullable=True)

    # Shims
    @property
    def priority_rank(self) -> int: return 100
    @priority_rank.setter
    def priority_rank(self, value): pass

    case: Mapped["RcmCase"] = relationship("RcmCase", back_populates="tasks")


class RcmFact(WorkflowBase):
    __tablename__ = "RCM_CASE_FACT"
    __table_args__ = (
        Index("ix_rcm_fact_case_key", "RCM_CASE_ID", "FACT_KEY"),
    )

    fact_id: Mapped[int] = mapped_column("RCM_CASE_FACT_ID", BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column("RCM_CASE_ID", BigInteger, nullable=False)
    fact_key: Mapped[str] = mapped_column("FACT_KEY", String(128), nullable=False)
    fact_value_str: Mapped[str | None] = mapped_column("FACT_VALUE_STR", String(1000))
    fact_value_num: Mapped[float | None] = mapped_column("FACT_VALUE_NUM", Numeric(18, 4))
    source_system: Mapped[str | None] = mapped_column("SOURCE", String(64))
    updated_at: Mapped[object] = mapped_column("UPDATED_AT", DateTime, server_default=func.now(), onupdate=func.now())

    # Shims
    @property
    def fact_scope(self) -> str: return "DEFAULT"
    @property
    def is_current(self) -> bool: return True


class RcmDocument(WorkflowBase):
    __tablename__ = "rcm_document"
    __table_args__ = (
        Index("ix_rcm_document_case_id", "case_id"),
        Index("ix_rcm_document_patient_id", "patient_id"),
        Index("ix_rcm_document_status_code", "status_code"),
    )

    document_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    clinic_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    patient_id: Mapped[int | None] = mapped_column(BigInteger)
    case_id: Mapped[int | None] = mapped_column(BigInteger)
    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(255))
    s3_bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128))
    sha256_hash: Mapped[str | None] = mapped_column(String(64))
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="RECEIVED")
    ocr_text: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    uploaded_at: Mapped[object] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[object] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class RcmEligibilityResult(WorkflowBase):
    __tablename__ = "rcm_eligibility_result"
    __table_args__ = (
        Index("ix_rcm_elg_case_id", "case_id"),
        Index("ix_rcm_elg_insurance_id", "insurance_id"),
    )

    eligibility_result_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    case_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    patient_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    insurance_id: Mapped[int | None] = mapped_column(BigInteger)
    verification_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    clearinghouse_name: Mapped[str | None] = mapped_column(String(64))
    payer_number: Mapped[str | None] = mapped_column(String(64))
    coverage_status: Mapped[str | None] = mapped_column(String(32))
    copay_amount: Mapped[float | None] = mapped_column(Numeric(10, 2))
    coinsurance_percent: Mapped[float | None] = mapped_column(Numeric(10, 2))
    deductible_amount: Mapped[float | None] = mapped_column(Numeric(10, 2))
    deductible_remaining_amount: Mapped[float | None] = mapped_column(Numeric(10, 2))
    family_deductible_amount: Mapped[float | None] = mapped_column(Numeric(10, 2))
    family_deductible_remaining_amount: Mapped[float | None] = mapped_column(Numeric(10, 2))
    out_of_pocket_amount: Mapped[float | None] = mapped_column(Numeric(10, 2))
    out_of_pocket_remaining: Mapped[float | None] = mapped_column(Numeric(10, 2))
    plan_begin_date: Mapped[object | None] = mapped_column(DateTime)
    plan_end_date: Mapped[object | None] = mapped_column(DateTime)
    subscriber_first_name: Mapped[str | None] = mapped_column(String(100))
    subscriber_last_name: Mapped[str | None] = mapped_column(String(100))
    subscriber_dob: Mapped[object | None] = mapped_column(DateTime)
    raw_request_json: Mapped[dict | None] = mapped_column(JSON)
    raw_response_json: Mapped[dict | None] = mapped_column(JSON)
    normalized_json: Mapped[dict | None] = mapped_column(JSON)
    result_code: Mapped[str] = mapped_column(String(64), nullable=False)
    result_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(DateTime, server_default=func.now())


class RcmStepHistory(WorkflowBase):
    __tablename__ = "RCM_STEP_HISTORY"
    __table_args__ = (
        Index("ix_rcm_step_history_case_id", "RCM_CASE_ID"),
        Index("ix_rcm_step_history_correlation_id", "CORRELATION_ID"),
    )

    step_history_id: Mapped[int] = mapped_column("RCM_STEP_HISTORY_ID", BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column("RCM_CASE_ID", BigInteger, nullable=False)
    correlation_id: Mapped[str] = mapped_column("CORRELATION_ID", String(128), nullable=False)
    trigger_type: Mapped[str] = mapped_column("TRIGGER_TYPE", String(32), nullable=False)
    handler_key: Mapped[str] = mapped_column("HANDLER_KEY", String(128), nullable=False)
    handler_version: Mapped[str] = mapped_column("HANDLER_VERSION", String(32), nullable=False, default="v1")
    state_before: Mapped[str | None] = mapped_column("STATE_BEFORE", String(64))
    state_after: Mapped[str | None] = mapped_column("STATE_AFTER", String(64))
    started_at: Mapped[object] = mapped_column("STARTED_AT", DateTime, server_default=func.now())
    ended_at: Mapped[object | None] = mapped_column("ENDED_AT", DateTime)
    outcome_code: Mapped[str] = mapped_column("OUTCOME_CODE", String(64), nullable=False)
    facts_considered_json: Mapped[dict | None] = mapped_column("FACTS_CONSIDERED_JSON", JSON)
    tools_invoked_json: Mapped[dict | None] = mapped_column("TOOLS_INVOKED_JSON", JSON)
    confidence_score: Mapped[float | None] = mapped_column("CONFIDENCE_SCORE", Numeric(5, 4))
    output_summary_json: Mapped[dict | None] = mapped_column("OUTPUT_SUMMARY_JSON", JSON)
    error_detail: Mapped[str | None] = mapped_column("ERROR_DETAIL", Text)
    created_at: Mapped[object] = mapped_column("CREATED_AT", DateTime, server_default=func.now())
