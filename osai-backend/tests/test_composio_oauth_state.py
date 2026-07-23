"""Composio OAuth callback state must be signed, bound, fresh, and single-use."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.routes import composio
from config import settings
from db.models import Base, Org, User


@pytest.fixture
def oauth_session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(Org(id="org-a", name="OAuth Test"))
        db.add(
            User(
                id="admin-a",
                org_id="org-a",
                email="oauth-admin@example.test",
                display_name="OAuth Admin",
                role="admin",
            )
        )
        db.commit()
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.mark.anyio
async def test_connect_uses_signed_state_bound_to_org_admin_and_toolkit(monkeypatch):
    fake = MagicMock()
    fake.connect = AsyncMock(return_value={"redirect_url": "https://provider.example/authorize"})
    fake.available.return_value = True
    monkeypatch.setattr(composio, "_client_or_404", lambda: fake)
    monkeypatch.setattr(settings, "public_base_url", "https://api.example.test")

    result = await composio.connect(
        "Notion",
        "org-a",
        {"sub": "admin-a", "org_id": "org-a", "role": "admin"},
    )
    assert result["redirect_url"] == "https://provider.example/authorize"
    callback_url = fake.connect.await_args.kwargs["callback_url"]
    query = parse_qs(urlsplit(callback_url).query)
    assert "org_id" not in query
    payload = composio._decode_oauth_state(query["state"][0])
    assert payload["org_id"] == "org-a"
    assert payload["admin_id"] == "admin-a"
    assert payload["toolkit"] == "notion"


@pytest.mark.anyio
async def test_callback_rejects_raw_tampered_and_expired_state():
    background = BackgroundTasks()
    db = MagicMock()
    with pytest.raises(HTTPException) as raw:
        await composio.callback(background, db, state=None, org_id="victim-org")
    assert raw.value.status_code == 400

    valid = composio._issue_oauth_state("org-a", "admin-a", "notion")
    with pytest.raises(HTTPException) as tampered:
        await composio.callback(background, db, state=valid + "x", org_id=None)
    assert tampered.value.status_code == 400

    expired = composio._issue_oauth_state(
        "org-a", "admin-a", "notion", ttl_seconds=-30
    )
    with pytest.raises(HTTPException) as old:
        await composio.callback(background, db, state=expired, org_id=None)
    assert old.value.status_code == 400


@pytest.mark.anyio
async def test_callback_requires_current_admin_and_consumes_state(
    monkeypatch, oauth_session_factory
):
    fake = MagicMock()
    fake.available.return_value = True
    monkeypatch.setattr(composio, "get_default_composio_client", lambda: fake)
    monkeypatch.setattr(settings, "frontend_url", "https://app.example.test")
    background = BackgroundTasks()
    state = composio._issue_oauth_state("org-a", "admin-a", "notion")

    with oauth_session_factory() as db:
        response = await composio.callback(background, db, state=state, org_id=None)
    assert response.headers["location"] == "https://app.example.test/integrations?connected=1"
    assert len(background.tasks) == 1
    assert background.tasks[0].args == ("org-a",)

    # A fresh session models another worker/process: the database uniqueness
    # constraint, not process-local memory, rejects the replay.
    with oauth_session_factory() as db, pytest.raises(HTTPException) as replay:
        await composio.callback(BackgroundTasks(), db, state=state, org_id=None)
    assert replay.value.status_code == 400
    assert "already been used" in replay.value.detail

    demoted_state = composio._issue_oauth_state("org-a", "admin-a", "slack")
    with oauth_session_factory() as db:
        db.get(User, "admin-a").role = "member"
        db.commit()
        with pytest.raises(HTTPException) as demoted:
            await composio.callback(
                BackgroundTasks(), db, state=demoted_state, org_id=None
            )
    assert demoted.value.status_code == 403


@pytest.mark.anyio
async def test_connect_rejects_mismatched_admin_org():
    with pytest.raises(HTTPException) as mismatch:
        await composio.connect(
            "notion",
            "org-a",
            {"sub": "admin-b", "org_id": "org-b", "role": "admin"},
        )
    assert mismatch.value.status_code == 403
