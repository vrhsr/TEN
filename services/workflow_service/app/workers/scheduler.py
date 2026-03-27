"""
APScheduler entrypoint.

Run with:
  python -m services.workflow_service.app.workers.scheduler

Two jobs:
  - charge_intake_job : polls every SCHEDULER_POLL_SECONDS (default 60s)
  - timer_wakeup_job  : runs every 30s to wake cases whose timer has expired
"""
import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.executors.pool import ThreadPoolExecutor as APThreadPoolExecutor

from shared.config import get_settings
from shared.logging import configure_logging, get_logger
from ..services.scheduler_service import SchedulerService

configure_logging()
log = get_logger(__name__)


def run_scheduler() -> None:
    settings = get_settings()
    svc = SchedulerService()

    executors = {
        "default": APThreadPoolExecutor(max_workers=4),
    }
    job_defaults = {
        "coalesce": True,          # merge missed runs
        "max_instances": 1,        # no overlapping runs of same job
        "misfire_grace_time": 30,
    }

    scheduler = BlockingScheduler(executors=executors, job_defaults=job_defaults)

    scheduler.add_job(
        svc.charge_intake_job,
        "interval",
        seconds=settings.scheduler_poll_seconds,
        id="demographics-charge-intake",
        replace_existing=True,
    )

    scheduler.add_job(
        svc.timer_wakeup_job,
        "interval",
        seconds=30,
        id="demographics-timer-wakeup",
        replace_existing=True,
    )

    def _shutdown(signum, frame):
        log.info("scheduler.shutdown_signal_received")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    log.info(
        "scheduler.starting",
        charge_intake_interval_s=settings.scheduler_poll_seconds,
        timer_wakeup_interval_s=30,
    )
    scheduler.start()


if __name__ == "__main__":
    run_scheduler()
