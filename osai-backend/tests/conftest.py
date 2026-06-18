"""Shared test fixtures.

Auth is enforced in production (org derived from a signed JWT; admin-gated
writes). Tests exercise endpoints without minting tokens, so we override the
auth dependencies to resolve to the demo org / an admin. This keeps production
strict while letting the suite call org-scoped endpoints directly.
"""

from __future__ import annotations

import pytest

from api.main import app
from db.session import get_org_id, require_admin


@pytest.fixture(autouse=True)
def _override_auth():
    app.dependency_overrides[get_org_id] = lambda: "demo-org"
    app.dependency_overrides[require_admin] = lambda: {
        "org_id": "demo-org",
        "role": "admin",
        "sub": "test-admin",
    }
    yield
    app.dependency_overrides.pop(get_org_id, None)
    app.dependency_overrides.pop(require_admin, None)
