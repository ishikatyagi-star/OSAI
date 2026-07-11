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
import logging

from workers.celery_app import celery_app

logger = logging.getLogger("osai.automations")


@celery_app.task(name="workers.tasks.automations.run_due_automations")
def run_due_automations() -> dict[str, object]:
    """Beat entrypoint: run everything that's due, one automation at a time."""
    return asyncio.run(_run_due())


async def _run_due() -> dict[str, object]:
    # Imported here so the Celery worker doesn't pay app-import cost at boot
    # (same pattern as the other task modules).
    from agent.automation_runner import execute_automation
    from db.repositories import list_due_automations
    from db.session import SessionLocal

    ran: list[str] = []
    failed: list[str] = []
    with SessionLocal() as db:
        for auto in list_due_automations(db):
            try:
                await execute_automation(db, auto)
                ran.append(auto.id)
            except Exception as exc:  # noqa: BLE001 — one bad automation must not block the rest
                logger.warning("Scheduled automation %s failed: %s", auto.id, exc)
                failed.append(auto.id)
    return {"ran": ran, "failed": failed}
