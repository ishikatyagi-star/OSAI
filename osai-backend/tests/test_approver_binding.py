"""Approver-binding regression tests (audit Medium #9).

Confirming a proposed action executes real connector side-effects, so approval
is bound to the user who proposed it or an org admin — any other org member is
refused even with a valid action ID. System context (no authenticated user)
keeps working for webhook/demo flows.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import agent.orchestrator as orch
from api.routes import agent as agent_route
from api.schemas.agent import ConfirmActionRequest, ConfirmActionResult


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _propose(user_id: str | None = "alice"):
    return orch._record(
        "demo-org",
        "internal",
        "osai",
        "create_automation",
        {"name": "T", "prompt": "P", "cadence": "daily"},
        "summary",
        user_id=user_id,
    )


@pytest.mark.anyio
async def test_other_member_cannot_approve():
    action = _propose(user_id="alice")
    result = await orch.confirm_action(
        action.id,
        "conv1",
        caller_org_id="demo-org",
        caller_user_id="bob",
        caller_is_admin=False,
    )
    assert result.status == "failed"
    assert result.error == "not_approver"


@pytest.mark.anyio
async def test_proposing_user_can_approve():
    action = _propose(user_id="alice")
    result = await orch.confirm_action(
        action.id,
        "conv1",
        caller_org_id="demo-org",
        caller_user_id="alice",
        caller_is_admin=False,
    )
    assert result.error != "not_approver"


@pytest.mark.anyio
async def test_admin_can_approve_any_action():
    action = _propose(user_id="alice")
    result = await orch.confirm_action(
        action.id,
        "conv1",
        caller_org_id="demo-org",
        caller_user_id="carol",
        caller_is_admin=True,
    )
    assert result.error != "not_approver"


@pytest.mark.anyio
async def test_system_context_still_confirms():
    action = _propose(user_id="alice")
    result = await orch.confirm_action(action.id, "conv1", caller_org_id="demo-org")
    assert result.error != "not_approver"


@pytest.mark.anyio
async def test_confirm_route_uses_current_database_role_not_stale_claim(monkeypatch):
    captured = {}

    class _Db:
        def get(self, model, user_id):
            return SimpleNamespace(id=user_id, org_id="demo-org", role="member")

    async def fake_confirm(*args, **kwargs):
        captured.update(kwargs)
        return ConfirmActionResult(
            id="action-1",
            status="failed",
            message="test",
            error="not_approver",
        )

    monkeypatch.setattr(agent_route, "confirm_action", fake_confirm)
    await agent_route.confirm(
        "action-1",
        ConfirmActionRequest(conversation_id="conv1"),
        _Db(),
        "demo-org",
        {"sub": "demoted-user", "org_id": "demo-org", "role": "admin"},
    )
    assert captured["caller_user_id"] == "demoted-user"
    assert captured["caller_is_admin"] is False
