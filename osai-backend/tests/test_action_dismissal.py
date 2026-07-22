from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import agent.orchestrator as orchestrator
import db.repositories as repositories
from api.main import app
from db.models import Base, ConnectorAction, ConnectorRecord, Org
from db.session import SessionLocal


def _propose(*, user_id: str | None = "alice"):
    with SessionLocal() as session:
        if session.get(Org, "demo-org") is None:
            session.add(Org(id="demo-org", name="Demo"))
            session.commit()
    return orchestrator._record(
        "demo-org",
        "connector",
        "freshdesk",
        "create_ticket",
        {"subject": "QA dismissal"},
        "Create a QA ticket",
        user_id=user_id,
        source_tiers=["normal"],
    )


def test_dismiss_is_durable_idempotent_and_blocks_later_confirm():
    action = _propose()

    result = orchestrator.dismiss_action(
        action.id,
        caller_org_id="demo-org",
        caller_user_id="alice",
    )

    assert result.status == "skipped"
    with SessionLocal() as session:
        assert session.get(ConnectorAction, action.id).status == "dismissed"

    orchestrator._PROPOSED.pop(action.id, None)  # simulate reload / another worker
    retry = orchestrator.dismiss_action(
        action.id,
        caller_org_id="demo-org",
        caller_user_id="alice",
    )
    assert retry.status == "skipped"
    assert retry.error is None

    confirmed = asyncio.run(
        orchestrator.confirm_action(
            action.id,
            "conversation",
            caller_org_id="demo-org",
            caller_user_id="alice",
        )
    )
    assert confirmed.status == "failed"
    assert confirmed.error == "unknown_action"


def test_only_requester_or_admin_can_dismiss():
    action = _propose()

    other_member = orchestrator.dismiss_action(
        action.id,
        caller_org_id="demo-org",
        caller_user_id="bob",
    )
    other_org = orchestrator.dismiss_action(
        action.id,
        caller_org_id="other-org",
        caller_user_id="alice",
    )

    assert other_member.error == "not_approver"
    assert other_org.error == "org_mismatch"
    with SessionLocal() as session:
        assert session.get(ConnectorAction, action.id).status == "proposed"

    admin = orchestrator.dismiss_action(
        action.id,
        caller_org_id="demo-org",
        caller_user_id="admin",
        caller_is_admin=True,
    )
    assert admin.status == "skipped"


def test_store_outage_keeps_dismissal_retryable(monkeypatch):
    action = _propose()
    monkeypatch.setattr(orchestrator, "dismiss_proposed_action", lambda _action_id: "unavailable")

    result = orchestrator.dismiss_action(
        action.id,
        caller_org_id="demo-org",
        caller_user_id="alice",
    )

    assert result.status == "failed"
    assert result.error == "approval_unavailable"
    assert action.id in orchestrator._PROPOSED
    with SessionLocal() as session:
        assert session.get(ConnectorAction, action.id).status == "proposed"


def test_store_outage_after_restart_keeps_dismissal_retryable(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "load_action_for_resolution",
        lambda _action_id: ("unavailable", None),
    )

    result = orchestrator.dismiss_action(
        "cache-empty-action",
        caller_org_id="demo-org",
        caller_user_id="alice",
    )

    assert result.status == "failed"
    assert result.error == "approval_unavailable"


def test_confirm_and_dismiss_have_exactly_one_atomic_winner(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'action-race.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(Org(id="race-org", name="Race org"))
        session.add(
            ConnectorRecord(
                key="freshdesk",
                display_name="Freshdesk",
                capabilities=["execute"],
            )
        )
        session.add(
            ConnectorAction(
                id="race-action",
                org_id="race-org",
                connector_key="freshdesk",
                action_type="create_ticket",
                status="proposed",
                payload={"org_id": "race-org"},
            )
        )
        session.commit()
    monkeypatch.setattr(repositories, "SessionLocal", factory)
    barrier = Barrier(2)

    def claim():
        barrier.wait()
        return repositories.claim_proposed_action("race-action")

    def dismiss():
        barrier.wait()
        return repositories.dismiss_proposed_action("race-action")

    with ThreadPoolExecutor(max_workers=2) as pool:
        claim_future = pool.submit(claim)
        dismiss_future = pool.submit(dismiss)
        outcomes = (claim_future.result(), dismiss_future.result())

    assert outcomes in (("claimed", "taken"), ("taken", "dismissed"))
    with factory() as session:
        expected = "consumed" if outcomes[0] == "claimed" else "dismissed"
        assert session.get(ConnectorAction, "race-action").status == expected
    engine.dispose()


def test_dismiss_endpoint_contract():
    action = _propose(user_id=None)

    response = TestClient(app).post(
        f"/ask/actions/{action.id}/dismiss",
        json={"conversation_id": "conversation"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": action.id,
        "status": "skipped",
        "message": "Action dismissed.",
        "error": None,
    }
