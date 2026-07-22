"""Recurring automation execution: due-selection logic and the beat task."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Automation, Base
from db.repositories import list_due_automations


def _sessionmaker():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _auto(session, **kw):
    defaults = dict(
        org_id="demo-org",
        name="a",
        prompt="do the thing",
        cadence="hourly",
        enabled=True,
        status="active",
    )
    defaults.update(kw)
    a = Automation(**defaults)
    session.add(a)
    session.commit()
    return a


NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC).replace(tzinfo=None)


def test_never_run_active_automation_is_due():
    session = _sessionmaker()()
    a = _auto(session)
    assert [d.id for d in list_due_automations(session, now=NOW)] == [a.id]


def test_recently_run_automation_is_not_due():
    session = _sessionmaker()()
    _auto(session, last_run_at=NOW - timedelta(minutes=30))  # hourly, ran 30m ago
    assert list_due_automations(session, now=NOW) == []


def test_stale_runs_are_due_per_cadence():
    session = _sessionmaker()()
    hourly = _auto(session, cadence="hourly", last_run_at=NOW - timedelta(hours=2))
    _auto(session, cadence="daily", last_run_at=NOW - timedelta(hours=2))  # not due
    weekly = _auto(session, cadence="weekly", last_run_at=NOW - timedelta(days=8))
    due = {d.id for d in list_due_automations(session, now=NOW)}
    assert due == {hourly.id, weekly.id}


def test_due_selection_survives_aware_now_vs_naive_last_run():
    # Production regression: now_utc() is tz-AWARE while last_run_at is stored in
    # a tz-naive column. The comparison must not raise (it 500'd the whole cron
    # tick before). Mirror prod by passing an aware `now` and a naive stored ts.
    session = _sessionmaker()()
    stale = _auto(session, cadence="hourly", last_run_at=NOW - timedelta(hours=2))
    _auto(session, cadence="hourly", last_run_at=NOW - timedelta(minutes=5))  # not due
    aware_now = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    due = {d.id for d in list_due_automations(session, now=aware_now)}
    assert due == {stale.id}


def test_manual_paused_draft_and_disabled_are_never_due():
    session = _sessionmaker()()
    _auto(session, cadence="manual")
    _auto(session, status="paused")
    _auto(session, status="draft")
    _auto(session, enabled=False)
    assert list_due_automations(session, now=NOW) == []


def test_scheduler_heartbeat_records_queue_proof(monkeypatch):
    monkeypatch.setattr(
        "workers.scheduler_health.write_scheduler_heartbeat",
        lambda: "2026-07-21T00:00:00+00:00",
    )
    from workers.tasks.automations import scheduler_heartbeat

    assert scheduler_heartbeat()["recorded_at"] == "2026-07-21T00:00:00+00:00"


async def test_beat_task_runs_due_automations_and_isolates_failures(monkeypatch):
    """_run_due executes every due automation via the shared runner; one failing
    automation must not stop the others."""
    maker = _sessionmaker()
    session = maker()
    a1_id = _auto(session, name="ok").id
    a2_id = _auto(session, name="boom").id
    a3_id = _auto(session, name="ok2").id
    session.close()

    executed: list[str] = []

    async def fake_execute(db, auto, **kw):
        if auto.name == "boom":
            raise RuntimeError("provider down")
        executed.append(auto.id)
        return {"id": auto.id}

    import agent.automation_runner as runner
    import db.session as db_session

    monkeypatch.setattr(runner, "execute_automation", fake_execute)
    monkeypatch.setattr(db_session, "SessionLocal", maker)

    # The loop moved to agent/automation_runner (shared by the Celery beat task
    # and the /internal cron endpoint); patch its collaborators on that module.
    result = await runner.run_due_automations()
    assert set(result["ran"]) == {a1_id, a3_id}
    assert result["failed"] == [a2_id]
    assert executed and len(executed) == 2
