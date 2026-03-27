from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from shared.logging import configure_logging
from .api.routes import router

configure_logging("orchestration")

app = FastAPI(
    title="Demographics Orchestration Service",
    version="1.0.0",
    description=(
        "LangGraph orchestration layer for the Demographics Agent. "
        "Receives advance_case calls from Temporal and the scheduler, "
        "runs the appropriate handler, and writes audit results."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/v1")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "orchestration"}
