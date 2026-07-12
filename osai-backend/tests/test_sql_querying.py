"""SQL answers: read-only guard, sources CRUD, schema, plan, execution."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.main import app
from api.routes.sql import ensure_readonly_select
from config import settings

client = TestClient(app)


def test_guard_allows_select_and_caps_rows():
    assert ensure_readonly_select("SELECT * FROM users").endswith("LIMIT 500")
    assert ensure_readonly_select("select 1 limit 5") == "select 1 limit 5"
    assert ensure_readonly_select("WITH t AS (SELECT 1) SELECT * FROM t -- c").startswith("WITH")
    # Trailing semicolon + comment is still one safe statement.
    assert ensure_readonly_select("SELECT 1; --x").startswith("SELECT 1")


@pytest.mark.parametrize(
    "bad",
    [
        "DELETE FROM users",
        "SELECT 1; DROP TABLE users",
        "UPDATE users SET role='admin'",
        "insert into users values (1)",
        "TRUNCATE users",
        "",
    ],
)
def test_guard_rejects_writes(bad):
    with pytest.raises(HTTPException):
        ensure_readonly_select(bad)


def _add_source() -> str:
    # The test database itself is a perfectly good Postgres source.
    resp = client.post(
        "/sql/sources", json={"name": "warehouse", "dsn": settings.database_url}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert ":***@" in body["dsn"] or "@" not in body["dsn"]  # password masked
    return body["id"]


def test_source_roundtrip_schema_and_execute():
    sid = _add_source()
    try:
        schema = client.get(f"/sql/sources/{sid}/schema").json()
        assert any(t["table"] == "orgs" for t in schema)

        run = client.post(
            "/sql/execute",
            json={"source_id": sid, "sql": "SELECT COUNT(*) AS n FROM orgs"},
        ).json()
        assert run["columns"] == ["n"] and run["row_count"] == 1

        # Write attempts are rejected before touching the database.
        assert (
            client.post(
                "/sql/execute", json={"source_id": sid, "sql": "DROP TABLE orgs"}
            ).status_code
            == 422
        )
    finally:
        client.delete(f"/sql/sources/{sid}")


def test_plan_uses_llm_and_sanitises():
    sid = _add_source()
    try:
        with patch(
            "llm.gemini.generate",
            new=AsyncMock(
                return_value="SQL:\nSELECT id FROM orgs\nEXPLANATION:\nAll org ids."
            ),
        ):
            plan = client.post(
                "/sql/plan", json={"source_id": sid, "question": "list org ids"}
            ).json()
        assert plan["sql"].startswith("SELECT id FROM orgs")
        assert plan["sql"].endswith("LIMIT 500")
        assert "org ids" in plan["explanation"]
    finally:
        client.delete(f"/sql/sources/{sid}")


def test_bad_dsn_rejected():
    assert (
        client.post("/sql/sources", json={"name": "x", "dsn": "mysql://nope"}).status_code
        == 422
    )
