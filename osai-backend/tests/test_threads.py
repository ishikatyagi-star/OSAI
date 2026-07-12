"""Persisted Ask threads: CRUD, sharing visibility, @-mention notifications."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _mk(title="Quarterly planning") -> str:
    resp = client.post("/threads", json={"title": title})
    assert resp.status_code == 200
    return resp.json()["id"]


def test_create_list_and_fetch_thread():
    tid = _mk()
    assert any(t["id"] == tid for t in client.get("/threads").json())

    r = client.post(f"/threads/{tid}/turns", json={"role": "user", "content": "Who owns infra?"})
    assert r.status_code == 200
    r = client.post(
        f"/threads/{tid}/turns",
        json={"role": "assistant", "content": "Priya owns infra.", "payload": {"citations": []}},
    )
    assert r.status_code == 200

    body = client.get(f"/threads/{tid}").json()
    assert [t["role"] for t in body["turns"]] == ["user", "assistant"]
    assert body["turns"][1]["payload"] == {"citations": []}


def test_share_toggle_and_rename():
    tid = _mk("before")
    body = client.patch(f"/threads/{tid}", json={"shared": True, "title": "after"}).json()
    assert body["shared"] is True and body["title"] == "after"


def test_turn_role_validated():
    tid = _mk()
    assert (
        client.post(f"/threads/{tid}/turns", json={"role": "system", "content": "x"}).status_code
        == 422
    )


def test_unknown_thread_404():
    assert client.get("/threads/nope").status_code == 404
    assert (
        client.post("/threads/nope/turns", json={"role": "user", "content": "x"}).status_code
        == 404
    )


def test_mention_notifies_member():
    from db.models import Notification, User
    from db.session import SessionLocal

    with SessionLocal() as s:
        member = s.query(User).filter(User.org_id == "demo-org").first()
        assert member is not None
        handle = (member.email or "").split("@")[0]

    tid = _mk("mention test")
    r = client.post(
        f"/threads/{tid}/turns",
        json={"role": "user", "content": f"@{handle} can you check this?"},
    )
    assert r.status_code == 200
    assert r.json()["mentioned"] >= 1

    with SessionLocal() as s:
        n = (
            s.query(Notification)
            .filter(Notification.user_id == member.id, Notification.type == "thread.mention")
            .order_by(Notification.created_at.desc())
            .first()
        )
        assert n is not None and n.payload["thread_id"] == tid
        # cleanup so reruns stay deterministic
        s.query(Notification).filter(Notification.type == "thread.mention").delete()
        s.commit()
