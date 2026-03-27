from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from shared.logging import configure_logging
from .api.routes import router

configure_logging("tools")

app = FastAPI(
    title="Demographics Tools Service",
    version="1.0.0",
    description=(
        "Tools/API layer for the Demographics Agent. "
        "All external integrations and database side-effects go through this service."
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
    return {"status": "ok", "service": "tools"}
