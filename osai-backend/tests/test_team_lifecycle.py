from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from api.main import app
from db.models import (
    AuditEvent,
    Automation,
    Base,
    Department,
    Invite,
    Notification,
    Org,
    SourceDocumentRecord,
    User,
)
from db.repositories import (
    accept_invite_by_token,
    create_invite,
    delete_department,
    delete_member,
    revoke_invite,
    update_department,
    update_member,
)
from db.session import require_admin


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _concurrent_sessions(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'team-integrity.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _race(factory, *operations):
    barrier = threading.Barrier(len(operations) + 1)

    def run(operation):
        with factory() as session:
            barrier.wait()
            try:
                return "ok", operation(session)
            except HTTPException as exc:
                return "http", exc.status_code

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        futures = [pool.submit(run, operation) for operation in operations]
        barrier.wait()
        return [future.result(timeout=15) for future in futures]


def _org(session, org_id: str = "org-A") -> None:
    session.add(Org(id=org_id, name=org_id))
    session.commit()


def _user(session, *, role: str, org_id: str = "org-A", department_id: str | None = None) -> User:
    user = User(
        id=f"user-{uuid.uuid4()}",
        org_id=org_id,
        email=f"{uuid.uuid4()}@example.test",
        display_name="Test User",
        role=role,
        department_id=department_id,
    )
    session.add(user)
    session.commit()
    return user


def test_revoking_invite_is_org_scoped_and_prevents_acceptance():
    session = _session()
    _org(session)
    _org(session, "org-B")
    invite = create_invite(session, "org-A", "invitee@example.test")

    assert revoke_invite(session, "org-B", invite.id) is False
    assert revoke_invite(session, "org-A", invite.id) is True
    assert session.get(Invite, invite.id).status == "revoked"
    assert accept_invite_by_token(session, invite.token, invite.email, "Invitee") is None


def test_invite_revoke_and_acceptance_are_atomic(tmp_path):
    engine, factory = _concurrent_sessions(tmp_path)
    with factory() as session:
        _org(session)
        invite = create_invite(session, "org-A", "race@example.test")
        invite_id = invite.id

    outcomes = _race(
        factory,
        lambda session: revoke_invite(session, "org-A", invite_id),
        lambda session: accept_invite_by_token(
            session, invite.token, "race@example.test", "Race User"
        )
        is not None,
    )

    assert sorted(outcomes) == [("ok", False), ("ok", True)]
    with factory() as session:
        invite = session.get(Invite, invite_id)
        assert invite.status in {"accepted", "revoked"}
        users = session.query(User).filter(User.email == "race@example.test").count()
        assert users == (1 if invite.status == "accepted" else 0)
    engine.dispose()


def test_member_removal_preserves_last_admin_and_removes_user_notifications():
    session = _session()
    _org(session)
    admin = _user(session, role="admin")
    member = _user(session, role="member")
    automation = Automation(
        org_id="org-A",
        user_id=member.id,
        name="Owned task",
        prompt="Do work",
        cadence="daily",
        trigger_token_hash="hash",
    )
    session.add(Notification(org_id="org-A", user_id=member.id, type="test"))
    session.add(automation)
    session.commit()

    assert (
        delete_member(
            session,
            member.id,
            "org-A",
            actor=admin.id,
            transfer_to_user_id=admin.id,
        )
        is True
    )
    assert session.get(User, member.id) is None
    assert session.query(Notification).filter_by(user_id=member.id).count() == 0
    session.refresh(automation)
    assert automation.enabled is False
    assert automation.status == "paused"
    assert automation.trigger_token_hash is None
    assert automation.user_id == admin.id
    audit = session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "team.member.removed")
    )
    assert audit.actor == admin.id
    assert audit.payload["paused_automations"] == 1
    assert audit.payload["transfer_to_user_id"] == admin.id

    with pytest.raises(HTTPException) as exc:
        delete_member(session, admin.id, "org-A")
    assert exc.value.status_code == 409
    assert session.get(User, admin.id) is not None


def test_concurrent_admin_demotion_and_removal_leave_one_admin(tmp_path):
    engine, factory = _concurrent_sessions(tmp_path)
    with factory() as session:
        _org(session)
        first = _user(session, role="admin")
        second = _user(session, role="admin")
        first_id, second_id = first.id, second.id

    outcomes = _race(
        factory,
        lambda session: update_member(
            session, first_id, "org-A", role="member"
        )
        is not None,
        lambda session: delete_member(
            session, second_id, "org-A", actor=first_id
        ),
    )

    assert sorted(outcomes) == [("http", 409), ("ok", True)]
    with factory() as session:
        assert session.query(User).filter_by(org_id="org-A", role="admin").count() == 1
    engine.dispose()


@pytest.mark.parametrize("usage", ["member", "invite", "document"])
def test_department_delete_returns_conflict_while_in_use(usage: str):
    session = _session()
    _org(session)
    department = Department(org_id="org-A", name="Engineering")
    session.add(department)
    session.commit()

    if usage == "member":
        _user(session, role="member", department_id=department.id)
    elif usage == "invite":
        session.add(
            Invite(
                org_id="org-A",
                email="invitee@example.test",
                department_id=department.id,
                status="pending",
                token="token",
            )
        )
        session.commit()
    else:
        session.add(
            SourceDocumentRecord(
                id="doc-1",
                org_id="org-A",
                source_type="test",
                external_id="external-1",
                title="Document",
                text="Body",
                department_id=department.id,
            )
        )
        session.commit()

    with pytest.raises(HTTPException) as exc:
        delete_department(session, "org-A", department.id)
    assert exc.value.status_code == 409
    assert session.get(Department, department.id) is not None


def test_department_rename_and_delete_are_org_scoped():
    session = _session()
    _org(session)
    _org(session, "org-B")
    department = Department(org_id="org-A", name="Old")
    session.add(department)
    session.commit()

    assert update_department(session, "org-B", department.id, "Wrong") is None
    assert update_department(session, "org-A", department.id, " New ").name == "New"
    assert delete_department(session, "org-B", department.id) is False
    assert delete_department(session, "org-A", department.id) is True


def test_department_delete_detaches_nonpending_invite_history():
    session = _session()
    _org(session)
    department = Department(org_id="org-A", name="Former team")
    invite = Invite(
        org_id="org-A",
        email="former@example.test",
        department_id=department.id,
        status="revoked",
        token="revoked-token",
    )
    session.add_all([department, invite])
    session.commit()

    assert delete_department(session, "org-A", department.id) is True
    session.refresh(invite)
    assert invite.department_id is None


def test_department_delete_and_assignment_cannot_leave_dangling_id(tmp_path):
    engine, factory = _concurrent_sessions(tmp_path)
    with factory() as session:
        _org(session)
        department = Department(org_id="org-A", name="Race")
        session.add(department)
        session.commit()
        member = _user(session, role="member")
        department_id, member_id = department.id, member.id

    outcomes = _race(
        factory,
        lambda session: delete_department(session, "org-A", department_id),
        lambda session: update_member(
            session, member_id, "org-A", department_id=department_id
        )
        is not None,
    )

    assert sum(outcome == ("ok", True) for outcome in outcomes) == 1
    assert any(outcome in {("http", 409), ("http", 422)} for outcome in outcomes)
    with factory() as session:
        member = session.get(User, member_id)
        department = session.get(Department, department_id)
        assert member.department_id is None or (
            department is not None and member.department_id == department.id
        )
    engine.dispose()


@pytest.mark.parametrize("usage", ["member", "document"])
def test_department_foreign_keys_restrict_direct_delete(tmp_path, usage: str):
    engine, factory = _concurrent_sessions(tmp_path)
    with factory() as session:
        _org(session)
        department = Department(org_id="org-A", name="Protected")
        session.add(department)
        session.commit()
        if usage == "member":
            _user(session, role="member", department_id=department.id)
        else:
            session.add(
                SourceDocumentRecord(
                    id="protected-doc",
                    org_id="org-A",
                    source_type="test",
                    external_id="protected",
                    title="Protected",
                    text="Body",
                    department_id=department.id,
                )
            )
            session.commit()

        session.delete(department)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert session.get(Department, department.id) is not None
    engine.dispose()


def test_member_department_can_be_unassigned_but_not_cross_workspace():
    session = _session()
    _org(session)
    _org(session, "org-B")
    own = Department(org_id="org-A", name="Own")
    foreign = Department(org_id="org-B", name="Foreign")
    session.add_all([own, foreign])
    session.commit()
    member = _user(session, role="member", department_id=own.id)

    assert update_member(session, member.id, "org-A", department_id=None).department_id is None
    with pytest.raises(HTTPException) as exc:
        update_member(session, member.id, "org-A", department_id=foreign.id)
    assert exc.value.status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        ("DELETE", "/team/invites/invite-id", None),
        ("DELETE", "/team/members/user-id", None),
        ("DELETE", "/team/departments/department-id", None),
        ("PATCH", "/team/departments/department-id", {"name": "New"}),
    ],
)
def test_team_lifecycle_routes_require_admin(method: str, path: str, json: dict | None):
    app.dependency_overrides.pop(require_admin, None)
    response = TestClient(app).request(method, path, json=json)
    assert response.status_code in (401, 403)
