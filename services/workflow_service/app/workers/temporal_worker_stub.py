"""
Temporal Workflow Stub
======================
This module provides a Temporal-compatible workflow and activity structure
that wraps the orchestration service's advance_case endpoint.

To activate real Temporal:
  1.  pip install temporalio
  2.  Replace this stub with the real workflow below.
  3.  Point TEMPORAL_HOST in .env to your Temporal cluster.
  4.  Run `python -m services.workflow_service.app.workers.temporal_worker_stub` as a worker process.

The stub is intentionally kept here so the scheduler can call the same interface
whether Temporal is active or not.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from shared.logging import get_logger
from ..core.clients import OrchestrationClient

log = get_logger(__name__)

# ── Temporal signal names ─────────────────────────────────────────────────────
SIGNAL_CASE_EVENT = "CASE_EVENT"
SIGNAL_DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
SIGNAL_TASK_COMPLETED = "TASK_COMPLETED"
SIGNAL_PATIENT_SELF_REGISTRATION_COMPLETED = "PATIENT_SELF_REGISTRATION_COMPLETED"
SIGNAL_HUMAN_REVIEW_COMPLETED = "HUMAN_REVIEW_COMPLETED"
SIGNAL_MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


@dataclass
class AdvanceTrigger:
    type: str
    correlation_id: str
    event_type: str | None = None


class DemographicsCaseWorkflowStub:
    """
    Stub that mimics a Temporal workflow execution model.
    Replace with a real temporalio.workflow decorated class when ready.
    """

    def __init__(self) -> None:
        self.orchestration = OrchestrationClient()

    def advance_case(self, case_id: int, trigger: AdvanceTrigger) -> dict:
        """
        Synchronous advance — used by the scheduler when Temporal is not running.
        """
        return self.orchestration.advance_case(
            case_id=case_id,
            correlation_id=trigger.correlation_id,
        )


# ── Real Temporal worker (activate when temporalio is installed) ──────────────
try:
    import temporalio  # noqa: F401
    _TEMPORAL_AVAILABLE = True
except ImportError:
    _TEMPORAL_AVAILABLE = False

if _TEMPORAL_AVAILABLE:
    from temporalio import workflow, activity
    from temporalio.client import Client
    from temporalio.worker import Worker

    TASK_QUEUE = "demographics-agent"

    @activity.defn(name="advance_case_activity")
    async def advance_case_activity(case_id: int, correlation_id: str) -> dict:
        """Temporal activity — calls the orchestration service."""
        client = OrchestrationClient()
        return client.advance_case(case_id=case_id, correlation_id=correlation_id)

    @workflow.defn(name="DemographicsWorkflow")
    class DemographicsWorkflow:
        def __init__(self) -> None:
            self._signal_received: bool = False
            self._signal_payload: dict = {}

        @workflow.signal(name=SIGNAL_CASE_EVENT)
        def on_case_event(self, payload: dict) -> None:
            self._signal_received = True
            self._signal_payload = payload

        @workflow.run
        async def run(self, case_id: int) -> dict:
            """
            Main workflow loop:
              1. Advance the case via the orchestration activity.
              2. Sleep until next_wake_at or until a signal arrives.
              3. Repeat until terminal state.
            """
            import datetime
            from temporalio.common import RetryPolicy

            while True:
                correlation_id = str(uuid.uuid4())
                result = await workflow.execute_activity(
                    advance_case_activity,
                    args=[case_id, correlation_id],
                    start_to_close_timeout=datetime.timedelta(seconds=120),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )

                next_state = result.get("state_after", "")
                from shared.constants import TERMINAL_STATES
                if next_state in TERMINAL_STATES:
                    return result

                next_wake_at_str = result.get("next_wake_at")
                if next_wake_at_str:
                    try:
                        wake_dt = datetime.datetime.fromisoformat(next_wake_at_str)
                        now = datetime.datetime.now(datetime.timezone.utc)
                        sleep_secs = max(0, (wake_dt - now).total_seconds())
                    except ValueError:
                        sleep_secs = 300
                else:
                    sleep_secs = 300  # default 5 minute poll

                # Sleep with signal interrupt
                try:
                    await asyncio.wait_for(
                        self._wait_for_signal(),
                        timeout=sleep_secs,
                    )
                except asyncio.TimeoutError:
                    pass  # Normal wake by timer

                self._signal_received = False

        async def _wait_for_signal(self) -> None:
            while not self._signal_received:
                await asyncio.sleep(1)

    async def run_temporal_worker() -> None:
        from shared.config import get_settings
        settings = get_settings()
        temporal_host = getattr(settings, "temporal_host", "localhost:7233")
        client = await Client.connect(temporal_host)
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[DemographicsWorkflow],
            activities=[advance_case_activity],
        )
        log.info("temporal_worker.starting", task_queue=TASK_QUEUE, host=temporal_host)
        await worker.run()

    if __name__ == "__main__":
        asyncio.run(run_temporal_worker())
