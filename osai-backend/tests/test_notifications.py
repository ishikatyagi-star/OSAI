from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from api.main import app
from db.models import Base, Notification, Org, User
from db.repositories import reset_org_content
from db.session import get_db, get_optional_claims, get_org_id, require_writable_org


@dataclass
class InboxContext:
    client: TestClient
    db: Session
    state: dict[str, Any]


@pytest.fixture
def inbox() -> InboxContext:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.add_all([Org(id="inbox-org", name="Inbox"), Org(id="other-org", name="Other")])
    session.add_all(
        [
            User(
                id="alice",
                org_id="inbox-org",
                email="alice@example.test",
                display_name="Alice",
                role="member",
            ),
            User(
                id="bob",
                org_id="inbox-org",
                email="bob@example.test",
                display_name="Bob",
                role="member",
            ),
            User(
                id="other",
                org_id="other-org",
                email="other@example.test",
                display_name="Other",
                role="member",
            ),
        ]
    )
    created_at = datetime(2026, 7, 22, 10, tzinfo=UTC)
    session.add_all(
        Notification(
            id=f"n-{index:03}",
            org_id="inbox-org",
            user_id="alice",
            type="thread.mention",
            payload={"thread_id": f"thread-{index}"},
            read=index % 2 == 1,
            created_at=created_at,
        )
        for index in range(53)
    )
    session.add_all(
        [
            Notification(
                id="bob-notice",
                org_id="inbox-org",
                user_id="bob",
                type="document.shared",
                read=False,
                created_at=created_at,
            ),
            Notification(
                id="other-notice",
                org_id="other-org",
                user_id="other",
                type="document.shared",
                read=False,
                created_at=created_at,
            ),
        ]
    )
    session.commit()

    state: dict[str, Any] = {"claims": {"sub": "alice"}}
    overrides = {
        get_db: lambda: session,
        get_org_id: lambda: "inbox-org",
        require_writable_org: lambda: "inbox-org",
        get_optional_claims: lambda: state["claims"],
    }
    missing = object()
    previous = {dep: app.dependency_overrides.get(dep, missing) for dep in overrides}
    app.dependency_overrides.update(overrides)
    client = TestClient(app)
    try:
        yield InboxContext(client, session, state)
    finally:
        client.close()
        for dependency, old in previous.items():
            if old is missing:
                app.dependency_overrides.pop(dependency, None)
            else:
                app.dependency_overrides[dependency] = old
        session.close()
        engine.dispose()


def test_notification_pages_are_stable_complete_and_user_scoped(inbox: InboxContext):
    expected = [f"n-{index:03}" for index in reversed(range(53))]
    found: list[str] = []
    cursor = None
    first_page = None

    while True:
        params = {"limit": 20}
        if cursor:
            params["cursor"] = cursor
        response = inbox.client.get("/notifications/page", params=params)
        assert response.status_code == 200
        page = response.json()
        first_page = first_page or page
        found.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert found == expected
    assert len(found) == len(set(found)) == 53
    assert first_page["total"] == 53
    assert first_page["unread_count"] == 27

    unread = inbox.client.get(
        "/notifications/page", params={"limit": 100, "unread_only": True}
    ).json()
    assert len(unread["items"]) == 27
    assert all(not item["read"] for item in unread["items"])
    assert unread["total"] == 53
    assert unread["unread_count"] == 27

    invalid = inbox.client.get("/notifications/page", params={"cursor": "bob-notice"})
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "Invalid notification cursor."
    read_cursor = inbox.client.get(
        "/notifications/page",
        params={"cursor": "n-051", "unread_only": True},
    )
    assert read_cursor.status_code == 422
    assert read_cursor.json()["detail"] == "Invalid notification cursor."


def test_mark_read_fails_closed_to_the_current_inbox(inbox: InboxContext):
    assert inbox.client.post("/notifications/bob-notice/read").status_code == 404
    assert inbox.db.get(Notification, "bob-notice").read is False

    inbox.state["claims"] = None
    assert inbox.client.post("/notifications/n-052/read").status_code == 401
    assert inbox.db.get(Notification, "n-052").read is False

    inbox.state["claims"] = {"sub": "alice"}
    response = inbox.client.post("/notifications/n-052/read")
    assert response.status_code == 200
    assert response.json()["read"] is True
    assert inbox.client.get("/notifications/page?limit=1").json()["unread_count"] == 26


def test_mark_all_read_is_idempotent_and_current_inbox_scoped(inbox: InboxContext):
    inbox.state["claims"] = None
    assert inbox.client.post("/notifications/read-all").status_code == 401
    assert (
        inbox.db.query(Notification)
        .filter(Notification.user_id == "alice", Notification.read.is_(False))
        .count()
        == 27
    )

    inbox.state["claims"] = {"sub": "alice"}
    response = inbox.client.post("/notifications/read-all")
    assert response.status_code == 200
    assert response.json() == {"updated": 27}
    assert inbox.client.get("/notifications/page?limit=1").json()["unread_count"] == 0
    assert inbox.db.get(Notification, "bob-notice").read is False
    assert inbox.db.get(Notification, "other-notice").read is False

    assert inbox.client.post("/notifications/read-all").json() == {"updated": 0}


def test_mentions_notify_only_after_the_thread_is_shared(inbox: InboxContext):
    created = inbox.client.post("/threads", json={"title": "Launch plan"})
    assert created.status_code == 200
    thread_id = created.json()["id"]

    private_turn = inbox.client.post(
        f"/threads/{thread_id}/turns",
        json={"role": "user", "content": "@bob keep this private"},
    )
    assert private_turn.status_code == 200
    assert private_turn.json()["mentioned"] == 0
    assert (
        inbox.db.query(Notification)
        .filter(
            Notification.user_id == "bob",
            Notification.type == "thread.mention",
            Notification.payload["thread_id"].as_string() == thread_id,
        )
        .count()
        == 0
    )

    assert inbox.client.patch(f"/threads/{thread_id}", json={"shared": True}).status_code == 200
    shared_turn = inbox.client.post(
        f"/threads/{thread_id}/turns",
        json={"role": "user", "content": "@bob now it is shared"},
    )
    assert shared_turn.status_code == 200
    assert shared_turn.json()["mentioned"] == 1
    assert (
        inbox.db.query(Notification)
        .filter(
            Notification.user_id == "bob",
            Notification.type == "thread.mention",
            Notification.payload["thread_id"].as_string() == thread_id,
        )
        .count()
        == 1
    )


def test_reset_removes_stale_document_notices_but_keeps_thread_mentions(inbox: InboxContext):
    inbox.db.add(
        Notification(
            id="alice-share",
            org_id="inbox-org",
            user_id="alice",
            type="document.shared",
            payload={"document_id": "deleted-document"},
        )
    )
    inbox.db.commit()

    counts = reset_org_content(inbox.db, "inbox-org")

    assert counts["notifications"] == 2
    assert inbox.db.get(Notification, "alice-share") is None
    assert inbox.db.get(Notification, "bob-notice") is None
    assert inbox.db.get(Notification, "n-052") is not None
    assert inbox.db.get(Notification, "other-notice") is not None
