"""Automation digest delivery to Slack (deliver_to / last_delivery)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agent.delivery import _format_message, deliver_result
from api.main import app

client = TestClient(app)


@pytest.fixture
def anyio_backend():
    return "asyncio"


# --- delivery module ---------------------------------------------------------


def test_format_message_truncates_long_results():
    msg = _format_message("Daily digest", "x" * 10_000)
    assert len(msg) < 4_000
    assert "truncated" in msg
    assert msg.startswith(":robot_face: *Daily digest*")


@pytest.mark.anyio
async def test_unsupported_target_is_skipped():
    res = await deliver_result("org-1", {"channel": "email", "target": "a@b.c"}, "n", "r")
    assert res["status"] == "skipped"


@pytest.mark.anyio
async def test_empty_result_is_skipped():
    res = await deliver_result("org-1", {"channel": "slack", "target": "#general"}, "n", "  ")
    assert res["status"] == "skipped"


@pytest.mark.anyio
async def test_composio_delivery_success():
    fake = MagicMock()
    fake.available.return_value = True
    fake.connection_identity = AsyncMock(return_value={"id": "c1"})
    fake.execute = AsyncMock(return_value={"successful": True, "data": {}, "error": None})
    with patch("connectors.composio_tool.get_default_composio_client", return_value=fake):
        res = await deliver_result(
            "org-1", {"channel": "slack", "target": "#ops"}, "Digest", "All good."
        )
    assert res == {"status": "delivered", "via": "composio", "target": "#ops"}
    slug, args, org = fake.execute.await_args.args
    assert slug == "SLACK_SEND_MESSAGE"
    assert args["channel"] == "#ops"
    assert "All good." in args["text"]
    assert org == "org-1"


@pytest.mark.anyio
async def test_falls_back_to_native_connector_and_reports_failure():
    fake = MagicMock()
    fake.available.return_value = False  # no Composio → native path
    native = MagicMock()
    native.execute_action = AsyncMock(
        return_value=MagicMock(status="failed", error="no token", url=None)
    )
    with (
        patch("connectors.composio_tool.get_default_composio_client", return_value=fake),
        patch("connectors.registry.connector_registry.get", return_value=native),
    ):
        res = await deliver_result(
            "org-1", {"channel": "slack", "target": "#ops"}, "Digest", "Content"
        )
    assert res["status"] == "failed"
    assert res["via"] == "native"


# --- API round-trip ----------------------------------------------------------


def test_create_update_and_clear_delivery_target():
    created = client.post(
        "/automations",
        json={
            "name": "Weekly brief",
            "prompt": "Summarize the week",
            "cadence": "weekly",
            "deliver_to": {"channel": "slack", "target": "#general"},
        },
    ).json()
    try:
        assert created["deliver_to"] == {"channel": "slack", "target": "#general"}

        updated = client.patch(
            f"/automations/{created['id']}",
            json={"deliver_to": {"channel": "slack", "target": "#ops"}},
        ).json()
        assert updated["deliver_to"]["target"] == "#ops"

        # Omitting deliver_to leaves it unchanged.
        untouched = client.patch(
            f"/automations/{created['id']}", json={"name": "Weekly brief v2"}
        ).json()
        assert untouched["deliver_to"]["target"] == "#ops"

        # Empty dict clears it.
        cleared = client.patch(
            f"/automations/{created['id']}", json={"deliver_to": {}}
        ).json()
        assert cleared["deliver_to"] is None
    finally:
        client.delete(f"/automations/{created['id']}")


def test_invalid_delivery_channel_rejected():
    resp = client.post(
        "/automations",
        json={
            "name": "X",
            "prompt": "Y",
            "deliver_to": {"channel": "carrier-pigeon", "target": "roof"},
        },
    )
    assert resp.status_code == 400
