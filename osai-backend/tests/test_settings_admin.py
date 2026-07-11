"""Data-routing settings admin gate (audit Medium #8).

Routing config decides which data tiers may reach cloud LLMs, so only org
admins may change it; any member can still read it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from api.main import app
from config import settings
from db.session import get_org_id, require_admin


@pytest.fixture
def real_auth_client():
    """Drop the suite's autouse auth overrides so these tests exercise the real
    JWT dependencies, then restore afterwards (conftest re-applies per test)."""
    app.dependency_overrides.pop(get_org_id, None)
    app.dependency_overrides.pop(require_admin, None)
    yield TestClient(app)


def _token(role: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": f"user-{role}",
            "org_id": "org-A",
            "role": role,
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def test_member_cannot_update_data_routing(real_auth_client):
    resp = real_auth_client.patch(
        "/settings/data-routing",
        json={"routing": {"red": "local", "amber": "local", "normal": "cloud"}},
        headers={"Authorization": f"Bearer {_token('member')}"},
    )
    assert resp.status_code == 403


def test_admin_can_update_data_routing(real_auth_client):
    resp = real_auth_client.patch(
        "/settings/data-routing",
        json={"routing": {"red": "local", "amber": "local", "normal": "cloud"}},
        headers={"Authorization": f"Bearer {_token('admin')}"},
    )
    assert resp.status_code == 200


def test_member_can_still_read_data_routing(real_auth_client):
    resp = real_auth_client.get(
        "/settings/data-routing",
        headers={"Authorization": f"Bearer {_token('member')}"},
    )
    assert resp.status_code == 200
