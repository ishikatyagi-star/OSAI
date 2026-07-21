"""Expired-connection handling in the integrations overlay + sync endpoint.

Regression for the "connected card but every sync 404s" trap: a Composio OAuth
token that has expired (common for Google apps in Testing publishing status,
which expire refresh tokens after ~7 days) must surface as "expired" (reconnect),
never as "connected".
"""

from __future__ import annotations

import pytest

import api.routes.integrations as integrations_routes


class _FakeComposio:
    def __init__(self, connections):
        self._connections = connections

    def available(self):
        return True

    async def list_connections(self, org_id):
        return self._connections

    async def toolkit_logo(self, slug):
        return None


@pytest.fixture
def _no_db(monkeypatch):
    # Force the DB fallback to an empty list so the overlay is the only source.
    monkeypatch.setattr(integrations_routes, "try_db", lambda name, fb, fn: [])


async def test_expired_only_connection_reads_expired(monkeypatch, _no_db):
    fake = _FakeComposio(
        [
            {"toolkit": "gmail", "status": "EXPIRED"},
            {"toolkit": "notion", "status": "ACTIVE"},
        ]
    )
    monkeypatch.setattr(integrations_routes, "get_default_composio_client", lambda: fake)
    items = await integrations_routes.list_integrations(db=None, org_id="org-1")
    by_key = {it["key"]: it["auth_state"] for it in items}
    assert by_key["gmail"] == "expired"
    assert by_key["google_drive" if "google_drive" in by_key else "notion"] == "connected"


async def test_active_wins_over_a_stale_duplicate(monkeypatch, _no_db):
    # Same toolkit connected twice (a re-auth): the ACTIVE one must win so the
    # card reads connected, not expired.
    fake = _FakeComposio(
        [
            {"toolkit": "gmail", "status": "EXPIRED"},
            {"toolkit": "gmail", "status": "ACTIVE"},
        ]
    )
    monkeypatch.setattr(integrations_routes, "get_default_composio_client", lambda: fake)
    items = await integrations_routes.list_integrations(db=None, org_id="org-1")
    gmail = next(it for it in items if it["key"] == "gmail")
    assert gmail["auth_state"] == "connected"
