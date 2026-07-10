from __future__ import annotations

import json

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api.routes.mcp as mcp
from api.main import app
from api.schemas.search import SearchResponse, SourceCitation
from config import settings
from db.models import Base, Org, User
import db.session as db_session


def _headers() -> dict[str, str]:
    token = jwt.encode(
        {"sub": "mcp-user", "org_id": "mcp-org", "role": "member"},
        settings.jwt_secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_mcp_requires_authentication():
    response = TestClient(app).post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response.status_code == 401


def test_mcp_initializes_and_lists_policy_annotated_tools():
    client = TestClient(app)
    initialized = client.post(
        "/mcp",
        headers=_headers(),
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    assert initialized.status_code == 200
    assert initialized.json()["result"]["capabilities"]["tools"] == {"listChanged": False}

    listed = client.post(
        "/mcp", headers=_headers(), json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    )
    tools = listed.json()["result"]["tools"]
    assert {tool["name"] for tool in tools} == {
        "osai_search",
        "osai_org_memory",
        "osai_propose_action",
        "osai_action_status",
    }
    assert next(tool for tool in tools if tool["name"] == "osai_propose_action")["_meta"]["osai_policy"]["approval"] == "required"


def test_mcp_search_uses_jwt_org_and_permission_scope(monkeypatch):
    captured = {}

    def _permissions(_db, _claims):
        return ["department:engineering"]

    def _clearance(_db, _claims):
        return "amber"

    async def _retrieve(request):
        captured["request"] = request
        return SearchResponse(
            answer="Scoped answer",
            citations=[SourceCitation(source_tool="notion", source_record_title="Engineering plan")],
            enough_context=True,
        )

    monkeypatch.setattr(mcp, "user_permissions", _permissions)
    monkeypatch.setattr(mcp, "user_clearance", _clearance)
    monkeypatch.setattr(mcp, "retrieve_answer", _retrieve)

    response = TestClient(app).post(
        "/mcp",
        headers=_headers(),
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "osai_search", "arguments": {"query": "What shipped?"}},
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert captured["request"].org_id == "mcp-org"
    assert captured["request"].requester_permissions == ["department:engineering"]
    assert captured["request"].requester_tier == "amber"
    assert json.loads(body["result"]["content"][0]["text"])["answer"] == "Scoped answer"


def test_mcp_api_key_is_scoped_to_its_issuing_user(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine)
    with test_session() as db:
        db.add(Org(id="mcp-org", name="MCP org"))
        db.add(
            User(
                id="mcp-user",
                org_id="mcp-org",
                email="mcp@example.com",
                display_name="MCP User",
                role="member",
            )
        )
        db.commit()
    monkeypatch.setattr(db_session, "SessionLocal", test_session)

    client = TestClient(app)
    created = client.post("/mcp/keys", headers=_headers(), json={"name": "Claude Code"})
    assert created.status_code == 201
    token = created.json()["token"]
    assert token.startswith("osai_mcp_")

    initialized = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    assert initialized.status_code == 200
