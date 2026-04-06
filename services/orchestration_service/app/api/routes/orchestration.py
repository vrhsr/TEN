# app/api/routes/orchestration.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.clients.workflow_engine_client import WorkflowEngineClient
from app.nodes.initialize import run_initialize
from shared.logging import get_logger

log = get_logger(__name__)

router = APIRouter(
    prefix="/orchestration",
    tags=["Orchestration"]
)


# ══════════════════════════════════════════════════════════
# Request Schema
# ══════════════════════════════════════════════════════════
class InitializeRequest(BaseModel):
    task_id: int


# ══════════════════════════════════════════════════════════
# POST /v1/orchestration/initialize
# ══════════════════════════════════════════════════════════
@router.post("/initialize")
def trigger_initialize(request: InitializeRequest):
    """
    Triggers the Initialize Demographics Node.

    Flow:
    - Node 1: Loads task + case + facts from 8082 API
    - Node 2: Checks for duplicate patient
    - Node 3: Decides next path based on demographics + insurance
    """
    log.info(
        "api.orchestration.initialize.trigger",
        task_id=request.task_id,
    )

    try:
        client = WorkflowEngineClient()

        result = run_initialize(
            task_id = request.task_id,
            client  = client,
        )

        return {
            "success" : True,
            "message" : "Initialize node completed successfully",
            "data"    : result
        }

    except Exception as e:
        log.error(
            "api.orchestration.initialize.failed",
            task_id=request.task_id,
            error=str(e),
        )
        raise HTTPException(
            status_code = 500,
            detail      = str(e)
        )