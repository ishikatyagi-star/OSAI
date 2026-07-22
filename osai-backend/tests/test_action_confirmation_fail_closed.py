"""Fail-closed regressions for durable proposed-action confirmation."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

import agent.orchestrator as orchestrator
import db.repositories as repositories
import db.session as db_session
from api.schemas.connector import ActionResult
from db.models import ConnectorAction, Org, now_utc
from db.session import SessionLocal

# Regression: proposed-action approval could execute without a durable claim.
# Found by /qa on 2026-07-22.
# Report: docs/qa-report-2026-07-22.md


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _demo_org_and_cache_cleanup():
    with SessionLocal() as session:
        if session.get(Org, "demo-org") is None:
            session.add(Org(id="demo-org", name="Demo"))
            session.commit()
    yield
    for action_id in list(orchestrator._PROPOSED):
        if action_id.startswith("qa-action-"):
            orchestrator._PROPOSED.pop(action_id, None)


class _NeverExecuteConnector:
    def __init__(self) -> None:
        self.calls = 0

    async def execute_action(self, _org_id, _action):
        self.calls += 1
        raise AssertionError("connector execution must remain behind the durable claim")


def _descriptor() -> dict:
    return {
        "org_id": "demo-org",
        "provider": "connector",
        "tool": "freshdesk",
        "action": "create_ticket",
        "payload": {"subject": "QA claim guard"},
        "summary": "Create a QA ticket",
        "user_id": None,
        "source_tiers": ["normal"],
    }


def _install_never_execute_connector(monkeypatch) -> _NeverExecuteConnector:
    connector = _NeverExecuteConnector()
    monkeypatch.setattr(orchestrator.connector_registry, "get", lambda _key: connector)
    return connector


@pytest.mark.anyio
async def test_expired_cached_approval_never_executes(monkeypatch):
    connector = _install_never_execute_connector(monkeypatch)
    action = orchestrator._record(
        "demo-org",
        "connector",
        "freshdesk",
        "create_ticket",
        _descriptor()["payload"],
        "Create a QA ticket",
        source_tiers=["normal"],
    )
    with SessionLocal() as session:
        row = session.get(ConnectorAction, action.id)
        assert row is not None
        row.created_at = (now_utc() - timedelta(hours=25)).replace(tzinfo=None)
        session.commit()

    result = await orchestrator.confirm_action(action.id, "conversation", caller_org_id="demo-org")

    assert result.status == "failed"
    assert result.error == "approval_expired"
    assert connector.calls == 0


@pytest.mark.anyio
async def test_expired_durable_approval_after_restart_never_executes(monkeypatch):
    connector = _install_never_execute_connector(monkeypatch)
    action = orchestrator._record(
        "demo-org",
        "connector",
        "freshdesk",
        "create_ticket",
        _descriptor()["payload"],
        "Create a QA ticket",
        source_tiers=["normal"],
    )
    with SessionLocal() as session:
        row = session.get(ConnectorAction, action.id)
        assert row is not None
        row.created_at = (now_utc() - timedelta(hours=25)).replace(tzinfo=None)
        session.commit()
    orchestrator._PROPOSED.pop(action.id, None)

    result = await orchestrator.confirm_action(action.id, "conversation", caller_org_id="demo-org")

    assert result.status == "failed"
    assert result.error == "unknown_action"
    assert connector.calls == 0


@pytest.mark.anyio
async def test_unpersisted_cached_approval_never_executes(monkeypatch):
    connector = _install_never_execute_connector(monkeypatch)

    def fail_save(*_args, **_kwargs):
        raise OperationalError("INSERT", {}, RuntimeError("database offline"))

    monkeypatch.setattr(orchestrator, "save_proposed_action", fail_save)
    action = orchestrator._record(
        "demo-org",
        "connector",
        "freshdesk",
        "create_ticket",
        _descriptor()["payload"],
        "Create a QA ticket",
        source_tiers=["normal"],
    )
    with SessionLocal() as session:
        assert session.get(ConnectorAction, action.id) is None

    result = await orchestrator.confirm_action(action.id, "conversation", caller_org_id="demo-org")

    assert result.status == "failed"
    assert result.error == "approval_not_persisted"
    assert connector.calls == 0


@pytest.mark.anyio
async def test_unavailable_claim_store_never_executes(monkeypatch):
    connector = _install_never_execute_connector(monkeypatch)
    action_id = f"qa-action-{uuid4()}"
    orchestrator._PROPOSED[action_id] = _descriptor()

    def unavailable_session():
        raise OperationalError("SELECT", {}, RuntimeError("database offline"))

    monkeypatch.setattr(repositories, "SessionLocal", unavailable_session)

    result = await orchestrator.confirm_action(action_id, "conversation", caller_org_id="demo-org")

    assert result.status == "failed"
    assert result.error == "approval_unavailable"
    assert connector.calls == 0
    assert action_id in orchestrator._PROPOSED


@pytest.mark.anyio
async def test_unavailable_store_after_restart_remains_retryable(monkeypatch):
    connector = _install_never_execute_connector(monkeypatch)
    action_id = f"qa-action-{uuid4()}"

    def unavailable_session():
        raise OperationalError("SELECT", {}, RuntimeError("database offline"))

    monkeypatch.setattr(repositories, "SessionLocal", unavailable_session)

    result = await orchestrator.confirm_action(
        action_id,
        "conversation",
        caller_org_id="demo-org",
    )

    assert result.status == "failed"
    assert result.error == "approval_unavailable"
    assert connector.calls == 0
    assert action_id not in orchestrator._PROPOSED


@pytest.mark.anyio
async def test_connector_failures_do_not_disclose_provider_errors(monkeypatch):
    marker = "provider-secret-password"

    class _FailingConnector:
        async def execute_action(self, _org_id, _action):
            return ActionResult(
                connector_key="freshdesk",
                status="failed",
                error=marker,
            )

    from llm import policy

    monkeypatch.setattr(orchestrator.connector_registry, "get", lambda _key: _FailingConnector())
    monkeypatch.setattr(orchestrator, "claim_proposed_action", lambda _action_id: "claimed")
    monkeypatch.setattr(policy, "load_data_routing", lambda _org_id: {})
    monkeypatch.setattr(policy, "connector_egress_allowed", lambda *_args: True)
    action_id = f"qa-action-{uuid4()}"
    orchestrator._PROPOSED[action_id] = _descriptor()

    result = await orchestrator.confirm_action(
        action_id,
        "conversation",
        caller_org_id="demo-org",
    )

    assert result.error == "connector_action_failed"
    assert marker not in result.model_dump_json()


def test_internal_action_exceptions_do_not_disclose_details(monkeypatch):
    marker = "internal-secret-password"

    def fail_session():
        raise RuntimeError(marker)

    monkeypatch.setattr(db_session, "SessionLocal", fail_session)

    result = orchestrator._execute_internal(
        "qa-internal-action",
        {
            "org_id": "demo-org",
            "action": "create_automation",
            "payload": {},
            "user_id": "alice",
        },
    )

    assert result.error == "internal_action_failed"
    assert marker not in result.model_dump_json()
