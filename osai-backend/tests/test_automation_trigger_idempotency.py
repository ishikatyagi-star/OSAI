from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from db.models import Automation, AutomationTriggerRequest, Base, Org, now_utc
from db.repositories import (
    AUTOMATION_TRIGGER_CLEANUP_LIMIT,
    cleanup_automation_trigger_requests,
    reserve_automation_trigger,
)


def _factory(database_url: str, **engine_kwargs):
    engine = create_engine(database_url, **engine_kwargs)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(Org(id="trigger-org", name="Triggers"))
        session.add(
            Automation(
                id="trigger-automation",
                org_id="trigger-org",
                name="Trigger test",
                prompt="Test",
                cadence="manual",
            )
        )
        session.commit()
    return factory


def test_concurrent_trigger_reservations_have_one_winner(tmp_path):
    factory = _factory(
        f"sqlite+pysqlite:///{tmp_path / 'trigger-reservations.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    barrier = Barrier(2)

    def reserve():
        with factory() as session:
            barrier.wait()
            outcome, _request = reserve_automation_trigger(
                session,
                automation_id="trigger-automation",
                org_id="trigger-org",
                idempotency_key="concurrent-trigger-key",
                request_hash="a" * 64,
            )
            return outcome

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _index: reserve(), range(2)))

    assert sorted(outcomes) == ["replay", "reserved"]


def test_trigger_idempotency_cleanup_is_retained_and_bounded():
    factory = _factory("sqlite+pysqlite:///:memory:")
    old = now_utc() - timedelta(days=8)
    with factory() as session:
        session.add_all(
            [
                AutomationTriggerRequest(
                    id=f"expired-{index}",
                    automation_id="trigger-automation",
                    org_id="trigger-org",
                    idempotency_key=f"expired-key-{index}",
                    request_hash="b" * 64,
                    status="completed",
                    response={"ok": True},
                    http_status=200,
                    created_at=old,
                    updated_at=old,
                )
                for index in range(AUTOMATION_TRIGGER_CLEANUP_LIMIT + 1)
            ]
        )
        session.commit()

        removed = cleanup_automation_trigger_requests(session)
        remaining = session.scalar(select(func.count()).select_from(AutomationTriggerRequest))

    assert removed == AUTOMATION_TRIGGER_CLEANUP_LIMIT
    assert remaining == 1
