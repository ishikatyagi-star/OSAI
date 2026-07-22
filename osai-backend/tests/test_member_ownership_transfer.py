from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from db.models import (
    AuditEvent,
    Automation,
    Base,
    Notification,
    Org,
    SavedArtifact,
    Thread,
    User,
    WorkflowRun,
)
from db.repositories import delete_member, get_member_removal_impact


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _user(session, org_id: str, role: str = "member") -> User:
    user = User(
        id=f"user-{uuid.uuid4()}",
        org_id=org_id,
        email=f"{uuid.uuid4()}@example.test",
        display_name="Test User",
        role=role,
    )
    session.add(user)
    session.commit()
    return user


def _owned_assets(session, owner: User) -> None:
    session.add_all(
        [
            Automation(
                org_id=owner.org_id,
                user_id=owner.id,
                name="Daily digest",
                prompt="Summarize",
                cadence="daily",
                trigger_token_hash="secret-hash",
            ),
            Thread(
                org_id=owner.org_id,
                created_by=owner.id,
                created_by_name=owner.email,
                title="Private",
                shared=False,
            ),
            Thread(
                org_id=owner.org_id,
                created_by=owner.id,
                created_by_name=owner.email,
                title="Shared",
                shared=True,
            ),
            SavedArtifact(
                org_id=owner.org_id,
                title="Pinned answer",
                data={"kind": "summary"},
                created_by=owner.id,
                created_by_name=owner.email,
            ),
            WorkflowRun(
                org_id=owner.org_id,
                created_by=owner.id,
                kind="meeting_action_items",
                status="complete",
                input_text="Meeting notes",
            ),
        ]
    )
    session.commit()


def test_removal_impact_counts_only_scoped_transferable_assets():
    session = _session()
    session.add_all([Org(id="org-A", name="A"), Org(id="org-B", name="B")])
    session.commit()
    owner = _user(session, "org-A")
    _owned_assets(session, owner)
    # Corrupt cross-org ownership must never be surfaced or reassigned by org A.
    session.add(
        Automation(
            org_id="org-B",
            user_id=owner.id,
            name="Other org",
            prompt="Do not expose",
            cadence="manual",
        )
    )
    session.commit()

    impact = get_member_removal_impact(session, owner.id, "org-A")

    assert impact is not None
    assert impact["assets"] == {
        "automations": 1,
        "private_threads": 1,
        "shared_threads": 1,
        "workflow_runs": 1,
    }
    assert impact["total_assets"] == 4
    assert impact["preserved"] == {"saved_artifacts": 1}
    assert impact["blocked"] is False
    assert impact["requires_transfer"] is True
    assert get_member_removal_impact(session, owner.id, "org-B") is None


def test_removal_requires_valid_same_org_transfer_before_mutating_assets():
    session = _session()
    session.add_all([Org(id="org-A", name="A"), Org(id="org-B", name="B")])
    session.commit()
    owner = _user(session, "org-A")
    foreign_target = _user(session, "org-B")
    _owned_assets(session, owner)

    with pytest.raises(HTTPException) as missing:
        delete_member(session, owner.id, "org-A")
    assert missing.value.status_code == 409
    assert missing.value.detail["code"] == "member_transfer_required"
    session.rollback()

    with pytest.raises(HTTPException) as cross_org:
        delete_member(
            session,
            owner.id,
            "org-A",
            transfer_to_user_id=foreign_target.id,
        )
    assert cross_org.value.status_code == 422
    session.rollback()

    automation = session.scalar(
        select(Automation).where(Automation.org_id == "org-A")
    )
    assert session.get(User, owner.id) is not None
    assert automation.user_id == owner.id
    assert automation.enabled is True
    assert automation.trigger_token_hash == "secret-hash"


def test_removal_transfers_assets_paused_and_audited_in_one_commit():
    session = _session()
    session.add(Org(id="org-A", name="A"))
    session.commit()
    admin = _user(session, "org-A", role="admin")
    owner = _user(session, "org-A")
    _owned_assets(session, owner)
    session.add(Notification(org_id="org-A", user_id=owner.id, type="test"))
    session.commit()

    assert delete_member(
        session,
        owner.id,
        "org-A",
        actor=admin.id,
        transfer_to_user_id=admin.id,
    )

    assert session.get(User, owner.id) is None
    automation = session.query(Automation).filter_by(org_id="org-A").one()
    assert automation.user_id == admin.id
    assert automation.enabled is False
    assert automation.status == "paused"
    assert automation.trigger_token_hash is None
    threads = session.query(Thread).filter_by(org_id="org-A").all()
    assert {thread.created_by for thread in threads} == {admin.id}
    assert {thread.created_by_name for thread in threads} == {owner.email}
    artifact = session.query(SavedArtifact).filter_by(org_id="org-A").one()
    assert artifact.created_by is None
    assert artifact.created_by_name == owner.email
    assert session.query(WorkflowRun).filter_by(created_by=admin.id).count() == 1
    assert session.query(Notification).filter_by(user_id=owner.id).count() == 0

    audit = session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "team.member.removed")
    )
    assert audit.actor == admin.id
    assert audit.payload["transfer_to_user_id"] == admin.id
    assert audit.payload["transferred_assets"] == {
        "automations": 1,
        "private_threads": 1,
        "shared_threads": 1,
        "workflow_runs": 1,
    }
    assert audit.payload["removed_notifications"] == 1
    assert audit.payload["detached_saved_artifacts"] == 1
