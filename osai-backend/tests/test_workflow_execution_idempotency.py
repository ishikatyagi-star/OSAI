from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.routes.workflow_actions import approve_item
from api.schemas.connector import ActionResult
from db.models import (
    ActionItemRecord,
    Base,
    ConnectorAction,
    ConnectorRecord,
    Org,
    User,
    WorkflowRun,
    now_utc,
)
from db.repositories import claim_action_item, workflow_action_execution_key
from llm.policy import DEFAULT_DATA_ROUTING


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _seed(session, *, item_id: str = "action-1") -> tuple[User, WorkflowRun, ActionItemRecord]:
    org = Org(id="execution-org", name="Execution")
    user = User(
        id="execution-user",
        org_id=org.id,
        email="execution@example.test",
        display_name="Executor",
        role="admin",
        permissions=["org:admin"],
    )
    run = WorkflowRun(
        id="execution-run",
        org_id=org.id,
        created_by=user.id,
        kind="meeting_action_items",
        status="needs_review",
        input_text="Create the incident ticket",
        destination="slack",
        data_tier="normal",
    )
    item = ActionItemRecord(
        id=item_id,
        workflow_run_id=run.id,
        title="Post incident update",
        destination="slack",
        status="needs_review",
    )
    session.add_all(
        [
            org,
            user,
            ConnectorRecord(
                key="slack",
                display_name="Slack",
                capabilities=["execute"],
            ),
            run,
            item,
        ]
    )
    session.commit()
    return user, run, item


async def _approve(session, user: User, run: WorkflowRun, item: ActionItemRecord):
    return await approve_item(
        run.id,
        item.id,
        session,
        run.org_id,
        {"sub": user.id, "org_id": run.org_id},
    )


@pytest.mark.anyio
async def test_provider_commit_then_timeout_is_not_reexecuted(monkeypatch):
    session = _session()
    user, run, item = _seed(session)

    class CommitThenTimeout:
        calls = 0
        keys: list[str | None] = []

        async def execute_action(self, _org_id, action):
            self.calls += 1
            self.keys.append(action.idempotency_key)
            raise TimeoutError("provider committed before response was lost")

    connector = CommitThenTimeout()
    monkeypatch.setattr("llm.policy.load_data_routing", lambda _org: DEFAULT_DATA_ROUTING)
    monkeypatch.setattr(
        "api.routes.workflow_actions.connector_registry.get",
        lambda _destination: connector,
    )

    first = await _approve(session, user, run, item)
    session.expire_all()
    second = await _approve(session, user, run, item)

    assert first["status"] == "outcome_unknown"
    assert first["reconciliation_required"] is True
    assert second["status"] == "outcome_unknown"
    assert connector.calls == 1
    assert connector.keys == [workflow_action_execution_key(item.id)]
    outbox = session.get(
        ConnectorAction,
        f"workflow-action:{workflow_action_execution_key(item.id)}",
    )
    assert outbox is not None and outbox.status == "outcome_unknown"


@pytest.mark.anyio
async def test_definite_preflight_failure_retries_with_same_provider_key(monkeypatch):
    session = _session()
    user, run, item = _seed(session)

    class ConfigureThenSucceed:
        keys: list[str | None] = []

        async def execute_action(self, _org_id, action):
            self.keys.append(action.idempotency_key)
            if len(self.keys) == 1:
                return ActionResult(
                    connector_key="slack",
                    status="skipped",
                    error="Slack token not configured.",
                )
            return ActionResult(
                connector_key="slack",
                status="succeeded",
                external_id="message-1",
                url="https://slack.test/message-1",
            )

    connector = ConfigureThenSucceed()
    monkeypatch.setattr("llm.policy.load_data_routing", lambda _org: DEFAULT_DATA_ROUTING)
    monkeypatch.setattr(
        "api.routes.workflow_actions.connector_registry.get",
        lambda _destination: connector,
    )

    first = await _approve(session, user, run, item)
    session.expire_all()
    second = await _approve(session, user, run, item)

    assert first["status"] == "failed_preflight"
    assert second["status"] == "completed"
    assert connector.keys == [
        workflow_action_execution_key(item.id),
        workflow_action_execution_key(item.id),
    ]


@pytest.mark.anyio
async def test_database_failure_after_provider_success_quarantines_retry(monkeypatch):
    import api.routes.workflow_actions as route

    session = _session()
    user, run, item = _seed(session)

    class SuccessfulProvider:
        calls = 0

        async def execute_action(self, _org_id, _action):
            self.calls += 1
            return ActionResult(connector_key="slack", status="succeeded")

    provider = SuccessfulProvider()
    real_update = route.update_action_item_execution
    update_calls = 0

    def fail_first_update(*args, **kwargs):
        nonlocal update_calls
        update_calls += 1
        if update_calls == 1:
            raise RuntimeError("database acknowledgement lost")
        return real_update(*args, **kwargs)

    monkeypatch.setattr("llm.policy.load_data_routing", lambda _org: DEFAULT_DATA_ROUTING)
    monkeypatch.setattr(route.connector_registry, "get", lambda _destination: provider)
    monkeypatch.setattr(route, "update_action_item_execution", fail_first_update)

    first = await _approve(session, user, run, item)
    session.expire_all()
    second = await _approve(session, user, run, item)

    assert first["status"] == "outcome_unknown"
    assert second["status"] == "outcome_unknown"
    assert provider.calls == 1


def test_stale_execution_claim_becomes_outcome_unknown():
    session = _session()
    _, _, item = _seed(session)
    item.status = "executing"
    item.execution_started_at = now_utc() - timedelta(hours=1)
    session.commit()

    assert claim_action_item(session, item_id=item.id, org_id="execution-org") == "unknown"
    assert session.get(ActionItemRecord, item.id).status == "outcome_unknown"


def test_concurrent_claims_have_one_winner(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'claims.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        _seed(session, item_id="concurrent-action")

    barrier = Barrier(2)

    def claim():
        with factory() as session:
            barrier.wait()
            return claim_action_item(
                session,
                item_id="concurrent-action",
                org_id="execution-org",
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: claim(), range(2)))

    assert sorted(results) == ["claimed", "taken"]
