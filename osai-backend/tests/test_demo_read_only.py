"""The shared demo workspace is read-only regardless of caller identity."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi import BackgroundTasks, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.main import app
from api.routes import composio
from api.routes.auth import _issue_token
from db.models import Base, Org, User
from db.session import get_db, require_admin
from llm.policy import DEFAULT_DATA_ROUTING


@dataclass(frozen=True)
class DemoApp:
    client: TestClient
    token: str
    factory: sessionmaker
    admin_id: str


@pytest.fixture
def demo_app() -> Iterator[DemoApp]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(Org(id="demo-org", name="Shared Demo"))
        admin = User(
            id="demo-admin",
            org_id="demo-org",
            email="demo-admin@example.test",
            display_name="Demo Admin",
            role="admin",
        )
        db.add(admin)
        db.commit()
        token = _issue_token(admin)

    def override_db():
        with factory() as db:
            yield db

    saved_overrides = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield DemoApp(client, token, factory, admin.id)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved_overrides)
        engine.dispose()


_UNSAFE_ROUTES = [
    ("POST", "/ask", {"question": "What changed?"}),
    ("POST", "/search", {"query": "roadmap"}),
    ("POST", "/team/departments", {"name": "QA"}),
    ("PATCH", "/settings/data-routing", {"routing": DEFAULT_DATA_ROUTING}),
    ("POST", "/integrations/composio/connect/notion", None),
    ("POST", "/evals", None),
    ("POST", "/orgs/demo-org/reset-content", None),
    ("DELETE", "/auth/account", None),
]


@pytest.mark.parametrize(("method", "path", "body"), _UNSAFE_ROUTES)
@pytest.mark.parametrize("identity", ["anonymous-header", "valid-demo-admin-jwt"])
def test_every_demo_route_category_rejects_unsafe_methods(
    demo_app: DemoApp,
    method: str,
    path: str,
    body: dict | None,
    identity: str,
) -> None:
    headers = (
        {"X-Org-Id": "demo-org"}
        if identity == "anonymous-header"
        else {"Authorization": f"Bearer {demo_app.token}"}
    )

    response = demo_app.client.request(method, path, json=body, headers=headers)

    assert response.status_code == 403, (identity, method, path, response.text)
    assert "read-only" in response.text
    with demo_app.factory() as db:
        assert db.get(User, demo_app.admin_id) is not None


@pytest.mark.parametrize(
    "path",
    ["/team/members", "/team/invites", "/settings/data-routing"],
)
def test_valid_demo_admin_can_still_read_safe_routes(
    demo_app: DemoApp,
    path: str,
) -> None:
    response = demo_app.client.get(
        path,
        headers={"Authorization": f"Bearer {demo_app.token}"},
    )
    assert response.status_code == 200, (path, response.text)


@pytest.mark.anyio
async def test_admin_dependency_preserves_head_as_a_safe_method(demo_app: DemoApp) -> None:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "HEAD",
            "scheme": "https",
            "path": "/team/invites",
            "raw_path": b"/team/invites",
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("api.example.test", 443),
        }
    )
    with demo_app.factory() as db:
        claims = {
            "sub": demo_app.admin_id,
            "org_id": "demo-org",
            "role": "admin",
            "tv": 0,
        }
        resolved = await require_admin(request, db, claims, None)
    assert resolved["org_id"] == "demo-org"
    assert resolved["role"] == "admin"


@pytest.mark.anyio
async def test_pending_composio_callback_cannot_mutate_demo_org(
    demo_app: DemoApp,
) -> None:
    state = composio._issue_oauth_state("demo-org", demo_app.admin_id, "notion")
    with demo_app.factory() as db, pytest.raises(HTTPException) as error:
        await composio.callback(BackgroundTasks(), db, state=state, org_id=None)
    assert error.value.status_code == 403
    assert "read-only" in error.value.detail
