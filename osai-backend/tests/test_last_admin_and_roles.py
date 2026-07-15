"""An org must never be left with nobody who can administer it (SHE-6 P1).

The org and its data outlive any one account, so losing the last admin strands a
workspace permanently: no team management, no integrations, no data sources, and
nobody left able to promote a replacement. Both routes that can remove the last
admin have to refuse.

Also: role is an enum. permissions_for_role reads anything that isn't "admin" as
a member, so an unvalidated string doesn't just sit in the column — a typo'd
"Admin" silently strips admin rights.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, Org, User
from db.repositories import count_admins, update_member


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _add_user(session, role: str, org_id: str = "org-A") -> str:
    if session.get(Org, org_id) is None:
        session.add(Org(id=org_id, name="A"))
    uid = f"user-{uuid.uuid4()}"
    session.add(
        User(
            id=uid,
            org_id=org_id,
            email=f"{uid}@t.test",
            display_name="T",
            role=role,
        )
    )
    session.commit()
    return uid


def test_cannot_demote_the_only_admin():
    """The bricking case: no admins left, and nobody able to promote one."""
    session = _session()
    admin_id = _add_user(session, "admin")
    _add_user(session, "member")

    with pytest.raises(HTTPException) as exc:
        update_member(session, admin_id, "org-A", role="member")

    assert exc.value.status_code == 409
    assert "only admin" in exc.value.detail
    assert session.get(User, admin_id).role == "admin"  # unchanged
    assert count_admins(session, "org-A") == 1


def test_can_demote_an_admin_when_another_remains():
    session = _session()
    first = _add_user(session, "admin")
    _add_user(session, "admin")

    user = update_member(session, first, "org-A", role="member")

    assert user.role == "member"
    assert count_admins(session, "org-A") == 1


def test_last_admin_of_one_org_is_unaffected_by_another_orgs_admins():
    """count_admins must be org-scoped, or a big neighbouring org would make
    every small org think it's safe to demote its only admin."""
    session = _session()
    admin_a = _add_user(session, "admin", org_id="org-A")
    _add_user(session, "admin", org_id="org-B")
    _add_user(session, "admin", org_id="org-B")

    with pytest.raises(HTTPException) as exc:
        update_member(session, admin_a, "org-A", role="member")
    assert exc.value.status_code == 409


def test_promoting_a_member_is_always_allowed():
    session = _session()
    _add_user(session, "admin")
    member_id = _add_user(session, "member")

    user = update_member(session, member_id, "org-A", role="admin")

    assert user.role == "admin"
    assert user.permissions == ["org:admin", "source:all"]
    assert count_admins(session, "org-A") == 2


def test_a_lone_admin_may_be_updated_without_changing_role():
    """The guard is about losing admin, not about touching the row at all."""
    session = _session()
    admin_id = _add_user(session, "admin")
    user = update_member(session, admin_id, "org-A", data_tier="red")
    assert user.data_tier == "red"
    assert user.role == "admin"


def test_re_setting_the_only_admin_to_admin_is_not_blocked():
    session = _session()
    admin_id = _add_user(session, "admin")
    assert update_member(session, admin_id, "org-A", role="admin").role == "admin"


@pytest.mark.parametrize("bad_role", ["superuser", "Admin", "ADMIN", "owner", ""])
def test_unknown_roles_are_rejected(bad_role):
    """Without this, the string lands in the column and permissions_for_role
    reads it as 'not admin' — so "Admin" silently demotes."""
    session = _session()
    _add_user(session, "admin")
    member_id = _add_user(session, "member")

    with pytest.raises(HTTPException) as exc:
        update_member(session, member_id, "org-A", role=bad_role)

    assert exc.value.status_code == 422
    assert session.get(User, member_id).role == "member"  # unchanged


# --- The other route that can remove the last admin: deleting your account ----


def test_only_admin_cannot_delete_their_own_account():
    """The org's data outlives the account, so the last admin leaving would
    strand a workspace nobody can administer."""
    import uuid as _uuid

    from fastapi.testclient import TestClient

    from api.main import app
    from api.routes.auth import _issue_token
    from db.session import SessionLocal, get_claims

    app.dependency_overrides.pop(get_claims, None)  # run the real auth
    org_id = f"org-{_uuid.uuid4()}"
    with SessionLocal() as s:
        s.add(Org(id=org_id, name="Solo"))
        s.commit()
        admin = User(
            id=f"user-{_uuid.uuid4()}",
            org_id=org_id,
            email=f"{_uuid.uuid4()}@t.test",
            display_name="Solo Admin",
            role="admin",
            token_version=0,
        )
        s.add(admin)
        s.commit()
        token = _issue_token(admin)
        admin_id = admin.id

    resp = TestClient(app).delete(
        "/auth/account", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 409
    assert "only admin" in resp.json()["detail"]
    with SessionLocal() as s:
        assert s.get(User, admin_id) is not None  # still there


def test_admin_can_delete_their_account_when_another_admin_remains():
    import uuid as _uuid

    from fastapi.testclient import TestClient

    from api.main import app
    from api.routes.auth import _issue_token
    from db.session import SessionLocal, get_claims

    app.dependency_overrides.pop(get_claims, None)
    org_id = f"org-{_uuid.uuid4()}"
    with SessionLocal() as s:
        s.add(Org(id=org_id, name="Duo"))
        s.commit()
        leaving = User(
            id=f"user-{_uuid.uuid4()}", org_id=org_id, email=f"{_uuid.uuid4()}@t.test",
            display_name="Leaving", role="admin", token_version=0,
        )
        s.add(leaving)
        s.add(User(
            id=f"user-{_uuid.uuid4()}", org_id=org_id, email=f"{_uuid.uuid4()}@t.test",
            display_name="Staying", role="admin", token_version=0,
        ))
        s.commit()
        token = _issue_token(leaving)
        leaving_id = leaving.id

    resp = TestClient(app).delete(
        "/auth/account", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    with SessionLocal() as s:
        assert s.get(User, leaving_id) is None
