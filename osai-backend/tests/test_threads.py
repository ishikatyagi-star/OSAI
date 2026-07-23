"""Persisted Ask threads: CRUD, sharing visibility, @-mention notifications."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

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
    body = client.get(f"/threads/{tid}").json()
    assert [t["role"] for t in body["turns"]] == ["user"]


def test_share_toggle_and_rename():
    tid = _mk("before")
    body = client.patch(f"/threads/{tid}", json={"shared": True, "title": "after"}).json()
    assert body["shared"] is True and body["title"] == "after"


def test_turn_role_validated():
    tid = _mk()
    for role in ("assistant", "system"):
        response = client.post(
            f"/threads/{tid}/turns", json={"role": role, "content": "forged"}
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "Only user turns may be created through this endpoint."


def test_ask_route_records_trusted_assistant_turn(monkeypatch):
    from api.routes import agent as agent_routes
    from api.schemas.agent import AskResponse
    from db.models import User
    from db.session import SessionLocal, get_optional_claims

    with SessionLocal() as session:
        user = session.query(User).filter(User.org_id == "demo-org").first()
        assert user is not None
        claims = {"sub": user.id, "email": user.email, "org_id": user.org_id, "role": user.role}

    app.dependency_overrides[get_optional_claims] = lambda: claims

    calls = 0

    async def _answer(*args, **kwargs) -> AskResponse:
        nonlocal calls
        calls += 1
        return AskResponse(
            conversation_id="trusted-conversation",
            answer="Priya owns infra.",
            enough_context=True,
            model_route="test",
        )

    monkeypatch.setattr(agent_routes, "run_ask", _answer)
    try:
        request_id = str(uuid4())
        response = client.post(
            "/ask", json={"question": "Who owns infra?", "request_id": request_id}
        )
        assert response.status_code == 200
        tid = response.json()["thread_id"]
        assert tid

        replay = client.post(
            "/ask", json={"question": "Who owns infra?", "request_id": request_id}
        )
        assert replay.status_code == 200
        assert replay.json() == response.json()
        assert calls == 1

        thread = client.get(f"/threads/{tid}").json()
        assert thread["created_by"] == user.id
        turns = thread["turns"]
        assert [turn["role"] for turn in turns] == ["user", "assistant"]
        assert turns[0]["content"] == "Who owns infra?"
        assert turns[1]["content"] == "Priya owns infra."
        assert turns[1]["author_name"] is None
        assert turns[1]["payload"]["provenance"] == "server-ask"
        assert turns[1]["payload"]["request_id"] == request_id
        assert turns[1]["payload"]["ask_response"] == response.json()
    finally:
        app.dependency_overrides.pop(get_optional_claims, None)


def test_ask_exchange_rolls_back_the_whole_pair_on_commit_failure(monkeypatch):
    from api.routes.threads import (
        record_ask_exchange,
        reserve_ask_exchange,
        store_ask_exchange_answer,
    )
    from api.schemas.agent import AskRequest, AskResponse
    from db.models import AskExchange, Thread, ThreadTurn, User
    from db.session import SessionLocal

    title = f"atomic-{uuid4()}"
    with SessionLocal() as session:
        user = session.query(User).filter(User.org_id == "demo-org").first()
        assert user is not None
        request_id = uuid4()
        request = AskRequest(
            org_id="demo-org", question=title, request_id=request_id
        )
        exchange, owns_lease = reserve_ask_exchange(
            session,
            org_id="demo-org",
            user_id=user.id,
            request_id=request_id,
            request_payload=request.model_dump(mode="json"),
        )
        assert owns_lease
        exchange = store_ask_exchange_answer(
            session,
            exchange,
            AskResponse(
                conversation_id="atomic-conversation",
                answer="Atomic answer",
                enough_context=True,
            ),
        )

        def _fail_commit() -> None:
            raise SQLAlchemyError("forced commit failure")

        monkeypatch.setattr(session, "commit", _fail_commit)
        with pytest.raises(SQLAlchemyError, match="forced commit failure"):
            record_ask_exchange(
                session,
                org_id="demo-org",
                user_id=user.id,
                user_email=user.email,
                row=exchange,
            )

        assert session.query(Thread).filter(Thread.title == title).count() == 0
        assert session.query(ThreadTurn).filter(ThreadTurn.content == title).count() == 0
        assert session.get(AskExchange, exchange.id).status == "answered"


def test_ask_persistence_failure_is_retriable_without_rerunning_model(monkeypatch):
    from api.routes import agent as agent_routes
    from api.schemas.agent import AskResponse
    from db.models import User
    from db.session import SessionLocal, get_optional_claims

    with SessionLocal() as session:
        user = session.query(User).filter(User.org_id == "demo-org").first()
        assert user is not None
        claims = {"sub": user.id, "email": user.email, "org_id": user.org_id}

    app.dependency_overrides[get_optional_claims] = lambda: claims
    model_calls = 0
    persist_calls = 0
    real_record = agent_routes.record_ask_exchange

    async def _answer(*args, **kwargs) -> AskResponse:
        nonlocal model_calls
        model_calls += 1
        return AskResponse(conversation_id="retry-conversation", answer="Retry answer")

    def _flaky_record(*args, **kwargs):
        nonlocal persist_calls
        persist_calls += 1
        if persist_calls == 1:
            raise SQLAlchemyError("temporary persistence failure")
        return real_record(*args, **kwargs)

    monkeypatch.setattr(agent_routes, "run_ask", _answer)
    monkeypatch.setattr(agent_routes, "record_ask_exchange", _flaky_record)
    request_id = str(uuid4())
    try:
        first = client.post(
            "/ask", json={"question": "Retry safely", "request_id": request_id}
        )
        assert first.status_code == 503
        assert first.headers["retry-after"] == "1"
        assert first.json()["detail"]["code"] == "ask_persistence_failed"

        retry = client.post(
            "/ask", json={"question": "Retry safely", "request_id": request_id}
        )
        assert retry.status_code == 200
        assert retry.json()["persistence_status"] == "saved"
        assert model_calls == 1
        assert persist_calls == 2
    finally:
        app.dependency_overrides.pop(get_optional_claims, None)


def test_inaccessible_thread_fails_before_model_execution(monkeypatch):
    from api.routes import agent as agent_routes
    from api.schemas.agent import AskResponse
    from db.models import Thread, ThreadTurn, User
    from db.session import SessionLocal, get_optional_claims

    with SessionLocal() as session:
        user = session.query(User).filter(User.org_id == "demo-org").first()
        assert user is not None
        claims = {"sub": user.id, "email": user.email, "org_id": user.org_id}
        thread = Thread(
            org_id="demo-org",
            created_by=f"other-{uuid4()}",
            title="private foreign thread",
        )
        session.add(thread)
        session.commit()
        thread_id = thread.id

    app.dependency_overrides[get_optional_claims] = lambda: claims
    model_calls = 0

    async def _answer(*args, **kwargs) -> AskResponse:
        nonlocal model_calls
        model_calls += 1
        return AskResponse(conversation_id="must-not-run", answer="no")

    monkeypatch.setattr(agent_routes, "run_ask", _answer)
    try:
        response = client.post(
            "/ask",
            json={
                "question": "Do not run",
                "thread_id": thread_id,
                "request_id": str(uuid4()),
            },
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "ask_thread_unavailable"
        assert model_calls == 0
        with SessionLocal() as session:
            assert (
                session.query(ThreadTurn)
                .filter(ThreadTurn.thread_id == thread_id)
                .count()
                == 0
            )
    finally:
        app.dependency_overrides.pop(get_optional_claims, None)


def test_concurrent_duplicate_waits_and_replays_one_model_run(monkeypatch):
    from api.routes import agent as agent_routes
    from api.schemas.agent import AskResponse
    from db.models import User
    from db.session import SessionLocal, get_optional_claims

    with SessionLocal() as session:
        user = session.query(User).filter(User.org_id == "demo-org").first()
        assert user is not None
        claims = {"sub": user.id, "email": user.email, "org_id": user.org_id}

    app.dependency_overrides[get_optional_claims] = lambda: claims
    model_calls = 0

    async def _answer(*args, **kwargs) -> AskResponse:
        nonlocal model_calls
        model_calls += 1
        await asyncio.sleep(0.3)
        return AskResponse(conversation_id="concurrent", answer="One answer")

    monkeypatch.setattr(agent_routes, "run_ask", _answer)
    request_id = str(uuid4())

    def _post():
        return client.post(
            "/ask", json={"question": "Run once", "request_id": request_id}
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: _post(), range(2)))
        assert [response.status_code for response in responses] == [200, 200]
        assert responses[0].json() == responses[1].json()
        assert model_calls == 1
    finally:
        app.dependency_overrides.pop(get_optional_claims, None)


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
    assert client.patch(f"/threads/{tid}", json={"shared": True}).status_code == 200
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


def test_private_thread_mention_does_not_notify_member():
    from db.models import Notification, User
    from db.session import SessionLocal

    with SessionLocal() as s:
        member = s.query(User).filter(User.org_id == "demo-org").first()
        assert member is not None
        handle = (member.email or "").split("@")[0]

    tid = _mk("private mention test")
    response = client.post(
        f"/threads/{tid}/turns",
        json={"role": "user", "content": f"@{handle} this stays private"},
    )
    assert response.status_code == 200
    assert response.json()["mentioned"] == 0

    with SessionLocal() as s:
        assert (
            s.query(Notification)
            .filter(
                Notification.user_id == member.id,
                Notification.type == "thread.mention",
                Notification.payload["thread_id"].as_string() == tid,
            )
            .count()
            == 0
        )
