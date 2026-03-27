from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from shared.config import get_settings

settings = get_settings()

workflow_engine = create_engine(
    settings.workflow_sqlalchemy_uri,
    echo=settings.sql_echo,
    pool_pre_ping=True,
    pool_size=settings.workflow_db_pool_size,
    max_overflow=settings.workflow_db_max_overflow,
)

claims_engine = create_engine(
    settings.allofactor_sqlalchemy_uri,
    pool_pre_ping=True,
    pool_size=settings.allofactor_db_pool_size,
    max_overflow=settings.allofactor_db_max_overflow,
)

WorkflowSessionLocal = sessionmaker(
    bind=workflow_engine, autoflush=False, autocommit=False
)
ClaimsSessionLocal = sessionmaker(
    bind=claims_engine, autoflush=False, autocommit=False
)
