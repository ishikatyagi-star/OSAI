"""External automation trigger API (tokened, PromptQL Program-API style)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _mk_automation() -> str:
    resp = client.post(
        "/automations",
        json={
            "name": "Pipeline risk report",
            "prompt": "List risky opportunities",
            "cadence": "manual",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_mint_trigger_and_revoke():
    aid = _mk_automation()
    minted = client.post(f"/automations/{aid}/token").json()
    token = minted["token"]
    assert token.startswith("osak_")

    # Listing shows presence, never the token itself.
    row = next(a for a in client.get("/automations").json() if a["id"] == aid)
    assert row["has_trigger_token"] is True

    with patch(
        "api.routes.automations.execute_automation",
        new=AsyncMock(return_value={"ok": True, "result": "2 risky opps"}),
    ):
        # External call: token only, no org auth.
        r = TestClient(app).post(
            f"/automations/{aid}/trigger", headers={"X-Trigger-Token": token}
        )
        assert r.status_code == 200 and r.json()["ok"] is True

        # Wrong/missing token → 401.
        assert (
            TestClient(app)
            .post(f"/automations/{aid}/trigger", headers={"X-Trigger-Token": "osak_wrong"})
            .status_code
            == 401
        )
        assert TestClient(app).post(f"/automations/{aid}/trigger").status_code == 401

    # Revoke kills external access.
    assert client.delete(f"/automations/{aid}/token").json()["revoked"] is True
    assert (
        TestClient(app)
        .post(f"/automations/{aid}/trigger", headers={"X-Trigger-Token": token})
        .status_code
        == 401
    )
    client.delete(f"/automations/{aid}")


def test_paused_automation_conflicts():
    aid = _mk_automation()
    token = client.post(f"/automations/{aid}/token").json()["token"]
    client.patch(f"/automations/{aid}", json={"status": "paused"})
    r = TestClient(app).post(
        f"/automations/{aid}/trigger", headers={"X-Trigger-Token": token}
    )
    assert r.status_code == 409
    client.delete(f"/automations/{aid}")
