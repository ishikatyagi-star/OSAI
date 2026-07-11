"""Approver-binding regression tests (audit Medium #9).

Confirming a proposed action executes real connector side-effects, so approval
is bound to the user who proposed it or an org admin — any other org member is
refused even with a valid action ID. System context (no authenticated user)
keeps working for webhook/demo flows.
"""

from __future__ import annotations

import pytest

import agent.orchestrator as orch


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
        caller_role="member",
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
        caller_role="member",
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
        caller_role="admin",
    )
    assert result.error != "not_approver"


@pytest.mark.anyio
async def test_system_context_still_confirms():
    action = _propose(user_id="alice")
    result = await orch.confirm_action(action.id, "conv1", caller_org_id="demo-org")
    assert result.error != "not_approver"
