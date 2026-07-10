import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from api.routes.automations import run_ as run_automation
from db.models import Automation, now_utc
from db.session import SessionLocal
from workers.celery_app import celery_app


@celery_app.task
def execute_connector_action(action_id: str) -> dict[str, str]:
    return {"action_id": action_id, "status": "queued"}


_INTERVALS = {
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
}


def _as_utc(value: datetime) -> datetime:
    """Normalize drivers that deserialize UTC columns without tzinfo (SQLite)."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@celery_app.task
def run_due_automations() -> dict[str, int]:
    """Run active non-manual automations whose cadence interval has elapsed."""
    now = now_utc()
    ran = 0
    failed = 0
    with SessionLocal() as db:
        automations = db.scalars(
            select(Automation).where(Automation.enabled.is_(True), Automation.status == "active")
        ).all()
        for automation in automations:
            interval = _INTERVALS.get(automation.cadence)
            if interval is None or (
                automation.last_run_at and now - _as_utc(automation.last_run_at) < interval
            ):
                continue
            try:
                asyncio.run(run_automation(automation.id, db, automation.org_id, None))
                ran += 1
            except Exception:  # noqa: BLE001 - one failed automation must not block the queue
                failed += 1
    return {"ran": ran, "failed": failed}
