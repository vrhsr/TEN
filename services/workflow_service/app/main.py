"""
Workflow Service entrypoint.
This process runs only the APScheduler — no HTTP server is needed.
Launch with: python -m services.workflow_service.app.main
"""
from shared.logging import configure_logging
from .workers.scheduler import run_scheduler

configure_logging()

if __name__ == "__main__":
    run_scheduler()
