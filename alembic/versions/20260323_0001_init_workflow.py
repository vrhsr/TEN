"""init workflow tables

Revision ID: 20260323_0001
Revises: None
Create Date: 2026-03-23
"""
from alembic import op
import sqlalchemy as sa

revision = "20260323_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rcm_case",
        sa.Column("case_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("case_type", sa.String(64), nullable=False),
        sa.Column("workflow_name", sa.String(64), nullable=False),
        sa.Column("workflow_version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("claim_id", sa.BigInteger()),
        sa.Column("clinic_id", sa.BigInteger()),
        sa.Column("facility_id", sa.BigInteger()),
        sa.Column("provider_id", sa.BigInteger()),
        sa.Column("patient_id", sa.BigInteger()),
        sa.Column("payer_id", sa.BigInteger()),
        sa.Column("visit_id", sa.BigInteger()),
        sa.Column("charge_id", sa.BigInteger()),
        sa.Column("state_code", sa.String(64), nullable=False),
        sa.Column("substate_code", sa.String(64)),
        sa.Column("step_code", sa.String(64)),
        sa.Column("queue_id", sa.String(64)),
        sa.Column("current_task_id", sa.BigInteger()),
        sa.Column("next_action_at", sa.DateTime()),
        sa.Column("due_at", sa.DateTime()),
        sa.Column("context_json", sa.JSON()),
        sa.Column("terminal_outcome_code", sa.String(64)),
        sa.Column("closed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("case_type", "charge_id", name="uq_demo_case"),
    )
    op.create_index("ix_rcm_case_patient_id", "rcm_case", ["patient_id"])
    op.create_index("ix_rcm_case_state_code", "rcm_case", ["state_code"])
    op.create_index("ix_rcm_case_claim_id", "rcm_case", ["claim_id"])
    op.create_index("ix_rcm_case_next_action_at", "rcm_case", ["next_action_at"])

    op.create_table(
        "rcm_task",
        sa.Column("task_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.BigInteger(), sa.ForeignKey("rcm_case.case_id"), nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("intent_key", sa.String(255), nullable=False),
        sa.Column("state_code", sa.String(32), nullable=False),
        sa.Column("priority_code", sa.String(32), nullable=False, server_default="normal"),
        sa.Column("priority_rank", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("queue_id", sa.String(64)),
        sa.Column("handler_key", sa.String(128)),
        sa.Column("next_action_at", sa.DateTime()),
        sa.Column("due_at", sa.DateTime()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_json", sa.JSON()),
        sa.Column("result_json", sa.JSON()),
        sa.Column("close_reason_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("case_id", "intent_key", name="uq_task_intent"),
    )
    op.create_index("ix_rcm_task_queue_state", "rcm_task", ["queue_id", "state_code"])
    op.create_index("ix_rcm_task_case_state", "rcm_task", ["case_id", "state_code"])

    op.create_table(
        "rcm_fact",
        sa.Column("fact_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("fact_scope", sa.String(32), nullable=False),
        sa.Column("fact_key", sa.String(128), nullable=False),
        sa.Column("fact_value_str", sa.String(1000)),
        sa.Column("fact_value_num", sa.Numeric(18, 4)),
        sa.Column("fact_value_bool", sa.Integer()),
        sa.Column("source_system", sa.String(64)),
        sa.Column("source_ref", sa.String(255)),
        sa.Column("confidence_score", sa.Numeric(5, 4)),
        sa.Column("is_current", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_rcm_fact_case_scope_key", "rcm_fact", ["case_id", "fact_scope", "fact_key"])
    op.create_index("ix_rcm_fact_case_current", "rcm_fact", ["case_id", "is_current"])

    op.create_table(
        "rcm_document",
        sa.Column("document_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("clinic_id", sa.BigInteger(), nullable=False),
        sa.Column("patient_id", sa.BigInteger()),
        sa.Column("case_id", sa.BigInteger()),
        sa.Column("document_type", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_ref", sa.String(255)),
        sa.Column("s3_bucket", sa.String(255), nullable=False),
        sa.Column("s3_key", sa.String(1024), nullable=False),
        sa.Column("mime_type", sa.String(128)),
        sa.Column("sha256_hash", sa.String(64)),
        sa.Column("status_code", sa.String(32), nullable=False, server_default="RECEIVED"),
        sa.Column("ocr_text", sa.Text()),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("uploaded_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_rcm_document_case_id", "rcm_document", ["case_id"])
    op.create_index("ix_rcm_document_patient_id", "rcm_document", ["patient_id"])
    op.create_index("ix_rcm_document_status_code", "rcm_document", ["status_code"])

    op.create_table(
        "rcm_step_history",
        sa.Column("step_history_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("handler_key", sa.String(128), nullable=False),
        sa.Column("handler_version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("state_before", sa.String(64)),
        sa.Column("state_after", sa.String(64)),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime()),
        sa.Column("outcome_code", sa.String(64), nullable=False),
        sa.Column("facts_considered_json", sa.JSON()),
        sa.Column("tools_invoked_json", sa.JSON()),
        sa.Column("confidence_score", sa.Numeric(5, 4)),
        sa.Column("output_summary_json", sa.JSON()),
        sa.Column("error_detail", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_rcm_step_history_case_id", "rcm_step_history", ["case_id"])
    op.create_index("ix_rcm_step_history_correlation_id", "rcm_step_history", ["correlation_id"])

    op.create_table(
        "rcm_eligibility_result",
        sa.Column("eligibility_result_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("patient_id", sa.BigInteger(), nullable=False),
        sa.Column("insurance_id", sa.BigInteger()),
        sa.Column("verification_mode", sa.String(32), nullable=False),
        sa.Column("clearinghouse_name", sa.String(64)),
        sa.Column("payer_number", sa.String(64)),
        sa.Column("coverage_status", sa.String(32)),
        sa.Column("copay_amount", sa.Numeric(10, 2)),
        sa.Column("coinsurance_percent", sa.Numeric(10, 2)),
        sa.Column("deductible_amount", sa.Numeric(10, 2)),
        sa.Column("deductible_remaining_amount", sa.Numeric(10, 2)),
        sa.Column("family_deductible_amount", sa.Numeric(10, 2)),
        sa.Column("family_deductible_remaining_amount", sa.Numeric(10, 2)),
        sa.Column("out_of_pocket_amount", sa.Numeric(10, 2)),
        sa.Column("out_of_pocket_remaining", sa.Numeric(10, 2)),
        sa.Column("plan_begin_date", sa.DateTime()),
        sa.Column("plan_end_date", sa.DateTime()),
        sa.Column("subscriber_first_name", sa.String(100)),
        sa.Column("subscriber_last_name", sa.String(100)),
        sa.Column("subscriber_dob", sa.DateTime()),
        sa.Column("raw_request_json", sa.JSON()),
        sa.Column("raw_response_json", sa.JSON()),
        sa.Column("normalized_json", sa.JSON()),
        sa.Column("result_code", sa.String(64), nullable=False),
        sa.Column("result_note", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_rcm_elg_case_id", "rcm_eligibility_result", ["case_id"])
    op.create_index("ix_rcm_elg_insurance_id", "rcm_eligibility_result", ["insurance_id"])


def downgrade() -> None:
    for table in [
        "rcm_eligibility_result",
        "rcm_step_history",
        "rcm_document",
        "rcm_fact",
        "rcm_task",
        "rcm_case",
    ]:
        op.drop_table(table)
