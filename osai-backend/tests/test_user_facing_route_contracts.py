from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.main import app
from api.routes import auth, graph, integrations, search, team
from api.schemas.connector import HealthcheckResult
from api.schemas.search import SearchResponse, SourceCitation
from db.models import Base, Org, User
from db.session import get_db, get_org_id, require_admin, require_writable_org

client = TestClient(app)


@pytest.fixture
def _real_auth():
    saved = {
        dependency: app.dependency_overrides.pop(dependency, None)
        for dependency in (get_org_id, require_admin)
    }
    yield
    for dependency, override in saved.items():
        if override is not None:
            app.dependency_overrides[dependency] = override


def test_auth_config_is_public_and_maps_deployment_flags(monkeypatch, _real_auth):
    monkeypatch.setattr(auth.settings, "google_oauth_client_id", "client")
    monkeypatch.setattr(auth.settings, "google_oauth_client_secret", "secret")
    monkeypatch.setattr(auth.settings, "google_oauth_redirect_uri", "https://example.test/callback")
    monkeypatch.setattr(auth.settings, "email_login_enabled", False)

    response = client.get("/auth/config")

    assert response.status_code == 200
    assert response.json() == {
        "google_enabled": True,
        "email_login_enabled": False,
    }


@pytest.mark.parametrize(
    "path",
    [
        "/graph/access",
        "/integrations/test-connector/healthcheck",
        "/team/members/member-1/removal-impact",
    ],
)
def test_protected_user_facing_routes_require_a_session(path: str, _real_auth):
    response = client.get(path)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required."}


def test_graph_access_maps_the_authenticated_org(monkeypatch):
    expected = {
        "users": [{"id": "member-1"}],
        "connectors": [{"key": "notion"}],
        "access": [{"user_id": "member-1", "connector_key": "notion"}],
    }
    seen: dict[str, object] = {}

    def build_access_graph(db, org_id):
        seen.update(db=db, org_id=org_id)
        return expected

    monkeypatch.setattr(graph, "build_access_graph", build_access_graph)

    response = client.get("/graph/access")

    assert response.status_code == 200
    assert response.json() == expected
    assert seen["org_id"] == "demo-org"
    assert hasattr(seen["db"], "query")


def test_graph_access_surfaces_provider_failure(monkeypatch):
    def fail(_db, _org_id):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(graph, "build_access_graph", fail)

    response = client.get("/graph/access")

    assert response.status_code == 503
    assert response.json() == {"detail": "The access map is temporarily unavailable."}


def test_connector_healthcheck_maps_native_result_and_org(monkeypatch):
    seen: dict[str, str] = {}

    class Connector:
        key = "test-connector"

        async def healthcheck(self, org_id: str) -> HealthcheckResult:
            seen["org_id"] = org_id
            return HealthcheckResult(
                connector_key=self.key,
                healthy=False,
                message="Credentials need attention.",
            )

    connector = Connector()
    monkeypatch.setattr(integrations.connector_registry, "all", lambda: [connector])
    monkeypatch.setattr(integrations.connector_registry, "get", lambda _key: connector)
    monkeypatch.setattr(
        integrations,
        "get_default_composio_client",
        lambda: SimpleNamespace(available=lambda: False),
    )

    response = client.get("/integrations/test-connector/healthcheck")

    assert response.status_code == 200
    assert response.json() == {
        "connector_key": "test-connector",
        "healthy": False,
        "message": "Credentials need attention.",
    }
    assert seen == {"org_id": "demo-org"}


def test_connector_healthcheck_maps_active_composio_connection(monkeypatch):
    seen: dict[str, str] = {}

    class Composio:
        def available(self):
            return True

        async def list_connections(self, org_id: str):
            seen["org_id"] = org_id
            return [{"toolkit": "gmail", "status": "ACTIVE"}]

    monkeypatch.setattr(integrations.connector_registry, "all", lambda: [])
    monkeypatch.setattr(integrations, "get_default_composio_client", Composio)

    response = client.get("/integrations/gmail/healthcheck")

    assert response.status_code == 200
    assert response.json() == {
        "connector_key": "gmail",
        "healthy": True,
        "message": "Connected via Composio (OAuth).",
    }
    assert seen == {"org_id": "demo-org"}


def test_connector_healthcheck_rejects_unknown_connector(monkeypatch):
    monkeypatch.setattr(integrations.connector_registry, "all", lambda: [])
    monkeypatch.setattr(
        integrations,
        "get_default_composio_client",
        lambda: SimpleNamespace(available=lambda: False),
    )

    response = client.get("/integrations/not-real/healthcheck")

    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown connector"}


def test_member_removal_impact_requires_admin():
    def deny_admin():
        raise HTTPException(status_code=403, detail="Admin role required.")

    original = app.dependency_overrides[require_admin]
    app.dependency_overrides[require_admin] = deny_admin
    try:
        response = client.get("/team/members/member-1/removal-impact")
    finally:
        app.dependency_overrides[require_admin] = original

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin role required."}


def test_member_removal_impact_maps_route_dependencies(monkeypatch):
    expected = {
        "member_id": "member-1",
        "member_email": "member@example.test",
        "member_display_name": "Test Member",
        "assets": {"automations": 1},
        "blockers": {"owned_uploads": 0},
        "preserved": {"saved_artifacts": 2},
        "total_assets": 1,
        "total_blockers": 0,
        "requires_transfer": True,
        "blocked": False,
    }
    seen: dict[str, object] = {}

    def removal_impact(db, user_id, org_id):
        seen.update(db=db, user_id=user_id, org_id=org_id)
        return expected

    monkeypatch.setattr(team, "get_member_removal_impact", removal_impact)

    response = client.get("/team/members/member-1/removal-impact")

    assert response.status_code == 200
    assert response.json() == expected
    assert seen["user_id"] == "member-1"
    assert seen["org_id"] == "demo-org"
    assert hasattr(seen["db"], "query")


def test_member_removal_impact_returns_not_found(monkeypatch):
    monkeypatch.setattr(team, "get_member_removal_impact", lambda _db, _user, _org: None)

    response = client.get("/team/members/missing/removal-impact")

    assert response.status_code == 404
    assert response.json() == {"detail": "Member not found"}


def test_search_binds_authenticated_request_and_maps_response(monkeypatch):
    marker = uuid.uuid4().hex
    org_id = f"search-org-{marker}"
    user_id = f"search-user-{marker}"
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        user = User(
            id=user_id,
            org_id=org_id,
            email=f"{user_id}@example.test",
            display_name="Search Member",
            role="member",
            permissions=["source:notion"],
            data_tier="amber",
        )
        db.add_all([Org(id=org_id, name="Search org"), user])
        db.commit()
        token = auth._issue_token(user)

    captured: dict[str, object] = {}

    async def retrieve_answer(request):
        captured.update(request.model_dump())
        return SearchResponse(
            answer="The roadmap is approved.",
            citations=[
                SourceCitation(
                    source_tool="notion",
                    source_record_title="Roadmap",
                    url="https://example.test/roadmap",
                    confidence=0.92,
                    data_tier="amber",
                    access_reason="Shared with this member",
                    model_routing="cloud",
                    routing_reason="Workspace policy allows amber data",
                )
            ],
            enough_context=True,
        )

    monkeypatch.setattr(search, "retrieve_answer", retrieve_answer)
    original_db = app.dependency_overrides.get(get_db)
    original_writable_org = app.dependency_overrides.pop(require_writable_org, None)

    def override_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        response = client.post(
            "/search",
            json={
                "org_id": "attacker-chosen-org",
                "query": "What is the roadmap status?",
                "requester_permissions": ["role:admin"],
                "requester_tier": "red",
                "requester_user_id": "attacker-chosen-user",
                "department_id": "department-requested",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        if original_db is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = original_db
        if original_writable_org is not None:
            app.dependency_overrides[require_writable_org] = original_writable_org
        engine.dispose()

    assert response.status_code == 200
    assert captured == {
        "org_id": org_id,
        "query": "What is the roadmap status?",
        "requester_permissions": ["source:notion", f"user:{user_id}"],
        "requester_tier": "amber",
        "requester_user_id": user_id,
        "department_id": "department-requested",
    }
    assert response.json() == {
        "answer": "The roadmap is approved.",
        "citations": [
            {
                "source_tool": "notion",
                "source_record_title": "Roadmap",
                "url": "https://example.test/roadmap",
                "confidence": 0.92,
                "data_tier": "amber",
                "access_reason": "Shared with this member",
                "model_routing": "cloud",
                "routing_reason": "Workspace policy allows amber data",
            }
        ],
        "enough_context": True,
    }


@pytest.mark.parametrize("query", ["", "   \r\n\t", "x" * 4_001])
def test_search_rejects_blank_or_oversized_queries(monkeypatch, query: str):
    called = False

    async def retrieve_answer(_request):
        nonlocal called
        called = True
        raise AssertionError("invalid input reached retrieval")

    monkeypatch.setattr(search, "retrieve_answer", retrieve_answer)

    response = client.post("/search", json={"query": query})

    assert response.status_code == 422
    assert called is False
