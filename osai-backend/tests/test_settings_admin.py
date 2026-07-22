"""Data-routing settings admin gate (audit Medium #8).

Routing config decides which data tiers may reach cloud LLMs, so only org
admins may change it; any member can still read it.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from api.main import app
from config import settings
from db.session import get_org_id, require_admin, require_writable_org
from llm.policy import DEFAULT_DATA_ROUTING


@pytest.fixture
def real_auth_client():
    """Drop the suite's autouse auth overrides so these tests exercise the real
    JWT dependencies, then restore afterwards (conftest re-applies per test).

    require_admin is now DB-backed (it rejects tokens for deleted/revoked users),
    so the token subjects must exist as real principals — seed them in org-A."""
    from db.models import Org, User
    from db.session import SessionLocal

    with SessionLocal() as s:
        if s.get(Org, "org-A") is None:
            s.add(Org(id="org-A", name="Org A"))
        for role in ("admin", "member"):
            uid = f"user-{role}"
            if s.get(User, uid) is None:
                s.add(
                    User(
                        id=uid,
                        org_id="org-A",
                        email=f"{uid}@org-a.test",
                        display_name=uid,
                        role=role,
                        token_version=0,
                    )
                )
        s.commit()

    app.dependency_overrides.pop(get_org_id, None)
    app.dependency_overrides.pop(require_writable_org, None)
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
        json={"routing": DEFAULT_DATA_ROUTING},
        headers={"Authorization": f"Bearer {_token('member')}"},
    )
    assert resp.status_code == 403


def test_admin_can_update_data_routing(real_auth_client):
    current = real_auth_client.get(
        "/settings/data-routing",
        headers={"Authorization": f"Bearer {_token('admin')}"},
    ).json()
    resp = real_auth_client.patch(
        "/settings/data-routing",
        json={"routing": DEFAULT_DATA_ROUTING, "expected_routing": current},
        headers={"Authorization": f"Bearer {_token('admin')}"},
    )
    assert resp.status_code == 200


def test_stale_admin_cannot_overwrite_newer_data_routing(real_auth_client):
    headers = {"Authorization": f"Bearer {_token('admin')}"}
    original = real_auth_client.get("/settings/data-routing", headers=headers).json()
    first = deepcopy(original)
    first["normal"]["llm_allowed"] = not first["normal"]["llm_allowed"]
    stale = deepcopy(original)
    stale["amber"]["llm_allowed"] = not stale["amber"]["llm_allowed"]

    assert (
        real_auth_client.patch(
            "/settings/data-routing",
            json={"routing": first, "expected_routing": original},
            headers=headers,
        ).status_code
        == 200
    )
    conflict = real_auth_client.patch(
        "/settings/data-routing",
        json={"routing": stale, "expected_routing": original},
        headers=headers,
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Data-routing policy changed; reload before saving."
    assert real_auth_client.get("/settings/data-routing", headers=headers).json() == first


def test_admin_cannot_store_malformed_data_routing(real_auth_client):
    resp = real_auth_client.patch(
        "/settings/data-routing",
        json={"routing": {"red": "local", "amber": "local", "normal": "cloud"}},
        headers={"Authorization": f"Bearer {_token('admin')}"},
    )
    assert resp.status_code == 422


def test_member_can_still_read_data_routing(real_auth_client):
    resp = real_auth_client.get(
        "/settings/data-routing",
        headers={"Authorization": f"Bearer {_token('member')}"},
    )
    assert resp.status_code == 200
