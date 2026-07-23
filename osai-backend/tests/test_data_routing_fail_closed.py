"""Fail-closed regressions for settings and external routing decisions."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

import agent.orchestrator as orchestrator
from api.main import app
from api.routes.workflow_actions import approve_item
from db.session import get_db
from llm.policy import (
    DEFAULT_DATA_ROUTING,
    DENY_ALL_DATA_ROUTING,
    cloud_llm_allowed,
    connector_egress_allowed,
    load_data_routing,
    normalize_data_routing,
)

# Regression: P1-05 - missing/unavailable routing provenance could reach external delivery.
# Found by /qa on 2026-07-22.
# Report: docs/qa-report-2026-07-22.md


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _policy_session(org):
    class PolicySession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, *_args):
            return org

    return PolicySession


def test_unknown_org_policy_is_deny_all(monkeypatch):
    import db.session as session_module

    monkeypatch.setattr(session_module, "SessionLocal", _policy_session(None))
    routing = load_data_routing(f"missing-org-{uuid4()}")
    assert routing == DENY_ALL_DATA_ROUTING
    assert cloud_llm_allowed(routing, "normal") is False
    assert connector_egress_allowed(routing, ["normal"], "slack") is False


def test_existing_org_without_override_uses_validated_defaults(monkeypatch):
    import db.session as session_module

    org = SimpleNamespace(data_routing=None)
    monkeypatch.setattr(session_module, "SessionLocal", _policy_session(org))
    assert load_data_routing("existing-org") == DEFAULT_DATA_ROUTING


def test_connector_destinations_are_normalized_and_validated():
    routing = deepcopy(DEFAULT_DATA_ROUTING)
    routing["normal"]["allowed_connectors"] = [" Slack ", "slack", "custom.tool"]
    normalized = normalize_data_routing(routing)
    assert normalized["normal"]["allowed_connectors"] == ["slack", "custom.tool"]

    routing["normal"]["allowed_connectors"] = ["not a slug"]
    with pytest.raises(ValueError):
        normalize_data_routing(routing)


@pytest.mark.parametrize(
    "stored_policy",
    [
        [],
        {"normal": {"llm_allowed": "true"}},
        {"future": {"allowed_connectors": ["slack"], "llm_allowed": True}},
    ],
)
def test_malformed_stored_policy_is_deny_all(monkeypatch, stored_policy):
    import db.session as session_module

    org = SimpleNamespace(data_routing=stored_policy)
    monkeypatch.setattr(session_module, "SessionLocal", _policy_session(org))
    assert load_data_routing("malformed-org") == DENY_ALL_DATA_ROUTING


def test_policy_store_outage_is_deny_all(monkeypatch):
    import db.session as session_module

    def unavailable_session():
        raise OperationalError("SELECT", {}, RuntimeError("database offline"))

    monkeypatch.setattr(session_module, "SessionLocal", unavailable_session)
    routing = load_data_routing("demo-org")
    assert routing == DENY_ALL_DATA_ROUTING
    assert cloud_llm_allowed(routing, "normal") is False


def test_settings_read_outage_returns_503_and_rolls_back():
    class BrokenSession:
        rolled_back = False

        def get(self, *_args):
            raise OperationalError("SELECT", {}, RuntimeError("database offline"))

        def rollback(self):
            self.rolled_back = True

    broken = BrokenSession()
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: broken
    try:
        response = TestClient(app).get("/settings/data-routing")
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous
    assert response.status_code == 503
    assert broken.rolled_back is True


def test_settings_commit_outage_never_echoes_policy_as_saved():
    class BrokenSession:
        rolled_back = False
        org = SimpleNamespace(data_routing=None)

        def get(self, *_args, **_kwargs):
            return self.org

        def commit(self):
            raise OperationalError("UPDATE", {}, RuntimeError("database offline"))

        def rollback(self):
            self.rolled_back = True

    broken = BrokenSession()
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: broken
    try:
        response = TestClient(app).patch(
            "/settings/data-routing",
            json={
                "routing": DEFAULT_DATA_ROUTING,
                "expected_routing": DEFAULT_DATA_ROUTING,
            },
        )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous
    assert response.status_code == 503
    assert broken.rolled_back is True


def test_invalid_stored_policy_can_only_be_recovered_to_deny_all():
    class InvalidPolicySession:
        org = SimpleNamespace(data_routing={"future": {}})
        committed = False

        def get(self, *_args, **_kwargs):
            return self.org

        def commit(self):
            self.committed = True

        def rollback(self):
            return None

    session = InvalidPolicySession()
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = TestClient(app).patch(
            "/settings/data-routing",
            json={"routing": DEFAULT_DATA_ROUTING, "expected_routing": None},
        )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous

    assert response.status_code == 409
    assert session.committed is False
    assert session.org.data_routing == {"future": {}}


def test_invalid_stored_policy_can_be_recovered_to_deny_all():
    class InvalidPolicySession:
        org = SimpleNamespace(data_routing={"future": {}})
        committed = False

        def get(self, *_args, **_kwargs):
            return self.org

        def commit(self):
            self.committed = True

        def rollback(self):
            return None

    session = InvalidPolicySession()
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = TestClient(app).patch(
            "/settings/data-routing",
            json={"routing": DENY_ALL_DATA_ROUTING, "expected_routing": None},
        )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous

    assert response.status_code == 200
    assert session.committed is True
    assert session.org.data_routing == DENY_ALL_DATA_ROUTING


def test_missing_expected_routing_cannot_overwrite_valid_policy():
    class ValidPolicySession:
        org = SimpleNamespace(data_routing=deepcopy(DEFAULT_DATA_ROUTING))
        committed = False

        def get(self, *_args, **_kwargs):
            return self.org

        def commit(self):
            self.committed = True

        def rollback(self):
            return None

    session = ValidPolicySession()
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = TestClient(app).patch(
            "/settings/data-routing",
            json={"routing": DENY_ALL_DATA_ROUTING},
        )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous

    assert response.status_code == 409
    assert session.committed is False
    assert session.org.data_routing == DEFAULT_DATA_ROUTING


@pytest.mark.anyio
async def test_ask_action_without_citation_provenance_is_not_claimed_or_executed(monkeypatch):
    import llm.policy as policy

    action_id = f"routing-action-{uuid4()}"
    orchestrator._PROPOSED[action_id] = {
        "org_id": "demo-org",
        "provider": "connector",
        "tool": "freshdesk",
        "action": "create_ticket",
        "payload": {"subject": "Unattributed action"},
        "summary": "Create an unattributed ticket",
        "user_id": None,
        "source_tiers": [],
    }
    connector_lookup = MagicMock()
    claim = MagicMock(return_value="claimed")
    monkeypatch.setattr(orchestrator.connector_registry, "get", connector_lookup)
    monkeypatch.setattr(orchestrator, "claim_proposed_action", claim)
    monkeypatch.setattr(policy, "load_data_routing", lambda _org_id: DEFAULT_DATA_ROUTING)
    try:
        result = await orchestrator.confirm_action(
            action_id,
            "conversation",
            caller_org_id="demo-org",
        )
        assert result.status == "failed"
        assert result.error == "delivery_policy_blocked"
        connector_lookup.assert_not_called()
        claim.assert_not_called()
        assert action_id in orchestrator._PROPOSED
    finally:
        orchestrator._PROPOSED.pop(action_id, None)


@pytest.mark.anyio
async def test_workflow_restricted_tier_is_blocked_before_claim(monkeypatch):
    import llm.policy as policy

    org_id = "workflow-routing-org"
    user_id = "routing-user"
    run_id = "routing-run"
    item_id = "routing-item"
    item = {
        "id": item_id,
        "title": "Do not deliver",
        "destination": "slack",
        "status": "needs_review",
    }
    run = {
        "id": run_id,
        "org_id": org_id,
        "created_by": user_id,
        "data_tier": "red",
        "action_items": [item],
    }
    connector_lookup = MagicMock()
    claim = MagicMock(return_value="claimed")
    monkeypatch.setattr(
        "api.routes.workflow_actions.get_workflow_run",
        lambda _db, _run_id: run,
    )
    monkeypatch.setattr(
        "api.routes.workflow_actions.current_org_actor",
        lambda _db, _org_id, _claims: (user_id, False),
    )
    monkeypatch.setattr("api.routes.workflow_actions.claim_action_item", claim)
    monkeypatch.setattr(
        "api.routes.workflow_actions.connector_registry.get",
        connector_lookup,
    )
    monkeypatch.setattr(policy, "load_data_routing", lambda _org_id: DEFAULT_DATA_ROUTING)
    with pytest.raises(HTTPException) as exc_info:
        await approve_item(
            run_id,
            item_id,
            MagicMock(),
            org_id,
            {"sub": user_id, "org_id": org_id},
        )
    assert exc_info.value.status_code == 403
    connector_lookup.assert_not_called()
    claim.assert_not_called()
    assert item["status"] == "needs_review"
