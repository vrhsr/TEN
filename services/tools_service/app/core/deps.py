from typing import Generator
from sqlalchemy.orm import Session
from ..db.session import WorkflowSessionLocal, ClaimsSessionLocal


def get_workflow_db() -> Generator[Session, None, None]:
    db = WorkflowSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_claims_db() -> Generator[Session, None, None]:
    db = ClaimsSessionLocal()
    try:
        yield db
    finally:
        db.close()
