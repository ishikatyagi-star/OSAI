"""Automation digest delivery to Slack (deliver_to / last_delivery)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from agent.delivery import _format_message, deliver_result
from api.main import app
from db.models import Org, User
from db.session import SessionLocal, get_optional_claims

client = TestClient(app)


@pytest.fixture(autouse=True)
def _automation_identity():
    with SessionLocal() as session:
        if session.get(Org, "demo-org") is None:
            session.add(Org(id="demo-org", name="Demo"))
        user = session.scalar(select(User).where(User.email == "automation-tests@osai.local"))
        if user is None:
            user = User(
                org_id="demo-org",
                email="automation-tests@osai.local",
                display_name="Automation Tests",
                role="admin",
                permissions=["org:admin", "source:all"],
            )
            session.add(user)
        session.commit()
        session.refresh(user)
        claims = {
            "sub": user.id,
            "org_id": user.org_id,
            "role": user.role,
            "tv": user.token_version,
        }
    previous = app.dependency_overrides.get(get_optional_claims)
    app.dependency_overrides[get_optional_claims] = lambda: claims
    yield
    if previous is None:
        app.dependency_overrides.pop(get_optional_claims, None)
    else:
        app.dependency_overrides[get_optional_claims] = previous


@pytest.fixture
def anyio_backend():
    return "asyncio"


# --- delivery module ---------------------------------------------------------


def test_format_message_truncates_long_results():
    msg = _format_message("Daily digest", "x" * 10_000)
    assert len(msg) < 4_000
    assert "truncated" in msg
    assert msg.startswith(":robot_face: *Daily digest*")


def test_format_message_neutralizes_slack_markup():
    msg = _format_message("Daily <ops>", "Ping <!channel> at <https://evil.example|here> ```")
    assert "<!channel>" not in msg
    assert "<https://" not in msg
    assert msg.count("```") == 2


@pytest.mark.anyio
async def test_unsupported_target_is_skipped():
    res = await deliver_result(
        "org-1", {"channel": "email", "target": "a@b.c"}, "n", "r", source_tiers=[]
    )
    assert res["status"] == "skipped"


@pytest.mark.anyio
async def test_empty_result_is_skipped():
    res = await deliver_result(
        "org-1", {"channel": "slack", "target": "#general"}, "n", "  ", source_tiers=[]
    )
    assert res["status"] == "skipped"


@pytest.mark.anyio
async def test_restricted_source_is_not_delivered():
    res = await deliver_result(
        "org-1",
        {"channel": "slack", "target": "#general"},
        "Digest",
        "Sensitive summary",
        source_tiers=["red"],
    )
    assert res["status"] == "skipped"
    assert "data-routing" in res["error"]


@pytest.mark.anyio
async def test_composio_delivery_success():
    fake = MagicMock()
    fake.available.return_value = True
    fake.connection_identity = AsyncMock(return_value={"id": "c1"})
    fake.execute = AsyncMock(return_value={"successful": True, "data": {}, "error": None})
    with patch("connectors.composio_tool.get_default_composio_client", return_value=fake):
        res = await deliver_result(
            "demo-org",
            {"channel": "slack", "target": "#ops"},
            "Digest",
            "All good.",
            source_tiers=["normal"],
        )
    assert res == {"status": "delivered", "via": "composio", "target": "#ops"}
    slug, args, org = fake.execute.await_args.args
    assert slug == "SLACK_SEND_MESSAGE"
    assert args["channel"] == "#ops"
    assert "All good." in args["text"]
    assert org == "demo-org"


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
            "demo-org",
            {"channel": "slack", "target": "#ops"},
            "Digest",
            "Content",
            source_tiers=["normal"],
        )
    assert res["status"] == "failed"
    assert res["via"] == "native"


@pytest.mark.anyio
async def test_missing_provenance_makes_no_delivery_provider_calls():
    composio_factory = MagicMock()
    native_get = MagicMock()
    with (
        patch(
            "connectors.composio_tool.get_default_composio_client",
            new=composio_factory,
        ),
        patch("connectors.registry.connector_registry.get", new=native_get),
    ):
        res = await deliver_result(
            "demo-org",
            {"channel": "slack", "target": "#ops"},
            "Digest",
            "Unattributed content",
            source_tiers=[],
        )
    assert res["status"] == "skipped"
    assert "data-routing" in res["error"]
    composio_factory.assert_not_called()
    native_get.assert_not_called()


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
