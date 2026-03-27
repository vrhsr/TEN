from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from shared.config import get_settings
# Import all models so Alembic can see them
from services.tools_service.app.models.workflow import (  # noqa: F401
    RcmCase, RcmTask, RcmFact, RcmDocument,
    RcmEligibilityResult, RcmStepHistory,
)
from services.tools_service.app.db.base import WorkflowBase

alembic_config = context.config
settings = get_settings()
alembic_config.set_main_option("sqlalchemy.url", settings.workflow_sqlalchemy_uri)

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

target_metadata = WorkflowBase.metadata


def run_migrations_offline() -> None:
    url = alembic_config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
