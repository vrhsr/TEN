from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Runtime
    app_env: str = "local"
    log_level: str = "INFO"
    sql_echo: bool = False

    # AWS
    aws_region: str = "us-east-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    s3_document_bucket: str = "demo-tenant-docs"

    # OpenAI
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"

    # OCR
    tesseract_cmd: str = "/usr/bin/tesseract"
    tessdata_prefix: str = "/usr/share/tesseract-ocr/4.00/tessdata"

    # allofactorv3 claims DB (read-only replica preferred)
    allofactor_db_host: str = "localhost"
    allofactor_db_port: int = 3306
    allofactor_db_name: str = "allofactorv3"
    allofactor_db_user: str = "root"
    allofactor_db_password: str = "secret"
    allofactor_db_pool_size: int = 5
    allofactor_db_max_overflow: int = 10

    # Workflow DB (read-write)
    workflow_db_host: str = "localhost"
    workflow_db_port: int = 3306
    workflow_db_name: str = "rcm_workflow"
    workflow_db_user: str = "root"
    workflow_db_password: str = "secret"
    workflow_db_pool_size: int = 5
    workflow_db_max_overflow: int = 10

    # Service URLs
    tools_base_url: str = "http://localhost:8001"
    orchestration_base_url: str = "http://localhost:8002"
    profile_engine_base_url: str = "http://localhost:8010"
    profile_engine_api_key: str = "dev-key"

    # Availity eligibility clearinghouse
    availity_base_url: str = "https://api.availity.com/availity/v1"
    availity_client_id: str | None = None
    availity_client_secret: str | None = None

    # Scheduler
    scheduler_poll_seconds: int = 60
    scheduler_batch_size: int = 100

    # Workflow business rules
    eligibility_freshness_days: int = 30
    self_reg_max_attempts: int = 3
    self_reg_first_attempt_wait_hours: int = 24
    self_reg_second_attempt_wait_hours: int = 48
    self_reg_third_attempt_wait_days: int = 7
    facesheet_max_attempts: int = 3
    facesheet_first_attempt_wait_hours: int = 24
    facesheet_second_attempt_wait_hours: int = 48
    facesheet_third_attempt_wait_days: int = 7

    # Internal auth
    internal_api_secret: str = "changeme"

    @property
    def allofactor_sqlalchemy_uri(self) -> str:
        return (
            f"mysql+pymysql://{self.allofactor_db_user}:{self.allofactor_db_password}"
            f"@{self.allofactor_db_host}:{self.allofactor_db_port}/{self.allofactor_db_name}"
            f"?charset=utf8mb4"
        )

    @property
    def workflow_sqlalchemy_uri(self) -> str:
        return (
            f"mysql+pymysql://{self.workflow_db_user}:{self.workflow_db_password}"
            f"@{self.workflow_db_host}:{self.workflow_db_port}/{self.workflow_db_name}"
            f"?charset=utf8mb4"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
