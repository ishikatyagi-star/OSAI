"""Scheduled execution of automations.

Celery beat fires `run_due_automations` on a fixed tick (see
`workers/celery_app.py`); each tick runs every active automation whose cadence
interval has elapsed, through the same runner as POST /automations/{id}/run.
`record_automation_run` stamps `last_run_at`, which is what makes the schedule
self-advancing — a failed run leaves the stamp untouched so the automation is
retried on the next tick.
"""

from __future__ import annotations

import asyncio

from workers.celery_app import celery_app


@celery_app.task(name="workers.tasks.automations.scheduler_heartbeat")
def scheduler_heartbeat() -> dict[str, str]:
    """Prove beat and the routed automation queue reached this worker."""
    from workers.scheduler_health import write_scheduler_heartbeat

    return {"recorded_at": write_scheduler_heartbeat()}


@celery_app.task(name="workers.tasks.automations.run_due_automations")
def run_due_automations() -> dict[str, object]:
    """Beat entrypoint: run everything that's due, one automation at a time."""
    # Imported here so the Celery worker doesn't pay app-import cost at boot
    # (same pattern as the other task modules). The actual loop lives in
    # agent/automation_runner so the /internal cron endpoint shares it.
    from agent.automation_runner import run_due_automations as run_due

    return asyncio.run(run_due())
