-- ============================================================
-- rcm_workflow database — Demographics Agent workflow state
-- Run once to bootstrap before Alembic takes over.
-- ============================================================

CREATE DATABASE IF NOT EXISTS rcm_workflow
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE rcm_workflow;

-- ── rcm_case ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rcm_case (
  case_id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  case_type          VARCHAR(64)     NOT NULL,
  workflow_name      VARCHAR(64)     NOT NULL,
  workflow_version   VARCHAR(32)     NOT NULL DEFAULT 'v1',
  claim_id           BIGINT          NULL,
  clinic_id          BIGINT          NULL,
  facility_id        BIGINT          NULL,
  provider_id        BIGINT          NULL,
  patient_id         BIGINT          NULL,
  payer_id           BIGINT          NULL,
  visit_id           BIGINT          NULL,
  charge_id          BIGINT          NULL,
  state_code         VARCHAR(64)     NOT NULL,
  substate_code      VARCHAR(64)     NULL,
  step_code          VARCHAR(64)     NULL,
  queue_id           VARCHAR(64)     NULL,
  current_task_id    BIGINT          NULL,
  next_action_at     DATETIME        NULL,
  due_at             DATETIME        NULL,
  context_json       JSON            NULL,
  terminal_outcome_code VARCHAR(64)  NULL,
  closed_at          DATETIME        NULL,
  created_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (case_id),
  UNIQUE KEY uq_demo_case (case_type, charge_id),
  KEY ix_rcm_case_patient_id    (patient_id),
  KEY ix_rcm_case_state_code    (state_code),
  KEY ix_rcm_case_claim_id      (claim_id),
  KEY ix_rcm_case_next_action_at (next_action_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── rcm_task ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rcm_task (
  task_id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  case_id            BIGINT UNSIGNED NOT NULL,
  task_type          VARCHAR(64)     NOT NULL,
  intent_key         VARCHAR(255)    NOT NULL,
  state_code         VARCHAR(32)     NOT NULL,
  priority_code      VARCHAR(32)     NOT NULL DEFAULT 'normal',
  priority_rank      INT             NOT NULL DEFAULT 100,
  queue_id           VARCHAR(64)     NULL,
  handler_key        VARCHAR(128)    NULL,
  next_action_at     DATETIME        NULL,
  due_at             DATETIME        NULL,
  attempt_count      INT             NOT NULL DEFAULT 0,
  payload_json       JSON            NULL,
  result_json        JSON            NULL,
  close_reason_code  VARCHAR(64)     NULL,
  created_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (task_id),
  CONSTRAINT fk_task_case FOREIGN KEY (case_id) REFERENCES rcm_case(case_id),
  UNIQUE KEY uq_task_intent (case_id, intent_key),
  KEY ix_rcm_task_queue_state (queue_id, state_code),
  KEY ix_rcm_task_case_state  (case_id, state_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── rcm_fact ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rcm_fact (
  fact_id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  case_id            BIGINT UNSIGNED NOT NULL,
  fact_scope         VARCHAR(32)     NOT NULL,
  fact_key           VARCHAR(128)    NOT NULL,
  fact_value_str     VARCHAR(1000)   NULL,
  fact_value_num     DECIMAL(18,4)   NULL,
  fact_value_bool    TINYINT(1)      NULL,
  source_system      VARCHAR(64)     NULL,
  source_ref         VARCHAR(255)    NULL,
  confidence_score   DECIMAL(5,4)    NULL,
  is_current         TINYINT(1)      NOT NULL DEFAULT 1,
  created_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (fact_id),
  KEY ix_rcm_fact_case_scope_key (case_id, fact_scope, fact_key),
  KEY ix_rcm_fact_case_current   (case_id, is_current)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── rcm_document ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rcm_document (
  document_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  clinic_id          BIGINT          NOT NULL,
  patient_id         BIGINT          NULL,
  case_id            BIGINT          NULL,
  document_type      VARCHAR(64)     NOT NULL,
  source_type        VARCHAR(64)     NOT NULL,
  source_ref         VARCHAR(255)    NULL,
  s3_bucket          VARCHAR(255)    NOT NULL,
  s3_key             VARCHAR(1024)   NOT NULL,
  mime_type          VARCHAR(128)    NULL,
  sha256_hash        VARCHAR(64)     NULL,
  status_code        VARCHAR(32)     NOT NULL DEFAULT 'RECEIVED',
  ocr_text           MEDIUMTEXT      NULL,
  metadata_json      JSON            NULL,
  uploaded_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (document_id),
  KEY ix_rcm_document_case_id    (case_id),
  KEY ix_rcm_document_patient_id (patient_id),
  KEY ix_rcm_document_status_code (status_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── rcm_step_history ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rcm_step_history (
  step_history_id    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  case_id            BIGINT UNSIGNED NOT NULL,
  correlation_id     VARCHAR(128)    NOT NULL,
  trigger_type       VARCHAR(32)     NOT NULL,
  handler_key        VARCHAR(128)    NOT NULL,
  handler_version    VARCHAR(32)     NOT NULL DEFAULT 'v1',
  state_before       VARCHAR(64)     NULL,
  state_after        VARCHAR(64)     NULL,
  started_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ended_at           DATETIME        NULL,
  outcome_code       VARCHAR(64)     NOT NULL,
  facts_considered_json JSON         NULL,
  tools_invoked_json    JSON         NULL,
  confidence_score      DECIMAL(5,4) NULL,
  output_summary_json   JSON         NULL,
  error_detail          MEDIUMTEXT   NULL,
  created_at         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (step_history_id),
  KEY ix_rcm_step_history_case_id       (case_id),
  KEY ix_rcm_step_history_correlation_id (correlation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── rcm_eligibility_result ───────────────────────────────────
CREATE TABLE IF NOT EXISTS rcm_eligibility_result (
  eligibility_result_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  case_id                       BIGINT UNSIGNED NOT NULL,
  patient_id                    BIGINT          NOT NULL,
  insurance_id                  BIGINT          NULL,
  verification_mode             VARCHAR(32)     NOT NULL,
  clearinghouse_name            VARCHAR(64)     NULL,
  payer_number                  VARCHAR(64)     NULL,
  coverage_status               VARCHAR(32)     NULL,
  copay_amount                  DECIMAL(10,2)   NULL,
  coinsurance_percent           DECIMAL(10,2)   NULL,
  deductible_amount             DECIMAL(10,2)   NULL,
  deductible_remaining_amount   DECIMAL(10,2)   NULL,
  family_deductible_amount      DECIMAL(10,2)   NULL,
  family_deductible_remaining_amount DECIMAL(10,2) NULL,
  out_of_pocket_amount          DECIMAL(10,2)   NULL,
  out_of_pocket_remaining       DECIMAL(10,2)   NULL,
  plan_begin_date               DATETIME        NULL,
  plan_end_date                 DATETIME        NULL,
  subscriber_first_name         VARCHAR(100)    NULL,
  subscriber_last_name          VARCHAR(100)    NULL,
  subscriber_dob                DATETIME        NULL,
  raw_request_json              JSON            NULL,
  raw_response_json             JSON            NULL,
  normalized_json               JSON            NULL,
  result_code                   VARCHAR(64)     NOT NULL,
  result_note                   TEXT            NULL,
  created_at                    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (eligibility_result_id),
  KEY ix_rcm_elg_case_id       (case_id),
  KEY ix_rcm_elg_insurance_id  (insurance_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
