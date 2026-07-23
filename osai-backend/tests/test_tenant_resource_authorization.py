"""Authorization regressions for workflow and document metadata resources.

These routes expose tenant-internal transcripts, connector side effects, private
document names, and sharing rosters.  Access therefore follows the current DB
principal, not a stale JWT role or same-org membership alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from api.main import app
from api.schemas.workflow_run import ActionItem, WorkflowRunResponse
from db.models import (
    ActionItemRecord,
    AuditEvent,
    Base,
    ConnectorAccount,
    ConnectorRecord,
    Department,
    Notification,
    Org,
    SourceDocumentRecord,
    User,
    WorkflowRun,
)
from db.repositories import (
    approve_action_item,
    cancel_action_item,
    claim_action_item,
    update_action_item_execution,
)
from db.session import get_db, get_optional_claims, get_org_id, require_writable_org

ORG_ID = "authz-org"


@dataclass
class AuthzContext:
    client: TestClient
    db: Session
    state: dict[str, Any]

    def as_user(self, user_id: str, *, claimed_role: str | None = None) -> None:
        user = self.db.get(User, user_id)
        assert user is not None
        self.state["claims"] = {
            "sub": user.id,
            "email": user.email,
            "org_id": user.org_id,
            "role": claimed_role or user.role,
            "tv": user.token_version or 0,
        }


@pytest.fixture
def authz() -> AuthzContext:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.add(Org(id=ORG_ID, name="Authorization Test Org"))
    session.add(Department(id="dept-eng", org_id=ORG_ID, name="Engineering"))
    session.add_all(
        [
            User(
                id="owner",
                org_id=ORG_ID,
                email="owner@example.test",
                display_name="Owner",
                role="member",
                department_id="dept-eng",
                permissions=[],
                data_tier="normal",
            ),
            User(
                id="other",
                org_id=ORG_ID,
                email="other@example.test",
                display_name="Other member",
                role="member",
                permissions=[],
                data_tier="normal",
            ),
            User(
                id="admin",
                org_id=ORG_ID,
                email="admin@example.test",
                display_name="Current admin",
                role="admin",
                permissions=["role:admin"],
                data_tier="normal",
            ),
            User(
                id="demoted",
                org_id=ORG_ID,
                email="demoted@example.test",
                display_name="Demoted admin",
                role="member",
                permissions=[],
                data_tier="normal",
            ),
        ]
    )
    session.commit()

    state: dict[str, Any] = {
        "org_id": ORG_ID,
        "claims": {
            "sub": "owner",
            "email": "owner@example.test",
            "org_id": ORG_ID,
            "role": "member",
            "tv": 0,
        },
    }
    overrides = {
        get_db: lambda: session,
        get_org_id: lambda: state["org_id"],
        require_writable_org: lambda: state["org_id"],
        get_optional_claims: lambda: state["claims"],
    }
    missing = object()
    previous = {dep: app.dependency_overrides.get(dep, missing) for dep in overrides}
    app.dependency_overrides.update(overrides)
    client = TestClient(app)
    try:
        yield AuthzContext(client=client, db=session, state=state)
    finally:
        client.close()
        for dep, old in previous.items():
            if old is missing:
                app.dependency_overrides.pop(dep, None)
            else:
                app.dependency_overrides[dep] = old
        session.close()
        engine.dispose()


def _seed_run(
    db: Session,
    run_id: str,
    *,
    created_by: str | None,
    item_ids: tuple[str, ...] = (),
) -> None:
    db.add(
        WorkflowRun(
            id=run_id,
            org_id=ORG_ID,
            created_by=created_by,
            kind="meeting_action_items",
            status="needs_review",
            input_text="Discuss the rollout and record an action item.",
            destination="manual",
            data_tier="normal",
            model_route="test",
        )
    )
    for item_id in item_ids:
        db.add(
            ActionItemRecord(
                id=item_id,
                workflow_run_id=run_id,
                title=f"Action {item_id}",
                destination="manual",
                status="needs_review",
            )
        )
    db.commit()


def _seed_document(
    db: Session,
    doc_id: str,
    *,
    permissions: list[str],
    tier: str = "normal",
    author: str | None = None,
) -> None:
    db.add(
        SourceDocumentRecord(
            id=doc_id,
            org_id=ORG_ID,
            source_type="upload",
            external_id=doc_id,
            title=f"{doc_id}.txt",
            author=author,
            text=f"contents of {doc_id}",
            permissions=permissions,
            data_tier=tier,
        )
    )
    db.commit()


def test_workflow_creation_persists_creator_and_scopes_list_and_get(authz, monkeypatch):
    runner_calls = []

    async def fake_run(run_id, **kwargs):
        runner_calls.append(kwargs)
        return WorkflowRunResponse(
            id=run_id,
            status="needs_review",
            model_route="test",
            action_items=[ActionItem(title="Follow up", destination="manual")],
        )

    monkeypatch.setattr("api.routes.workflows.run_action_item_workflow", fake_run)
    created = authz.client.post(
        "/workflows",
        json={"input_text": "Owner will follow up.", "destination": "manual"},
    )
    assert created.status_code == 200
    run_id = created.json()["id"]
    assert runner_calls[0]["actor_user_id"] == "owner"
    assert runner_calls[0]["viewer_is_admin"] is False
    assert authz.db.get(WorkflowRun, run_id).created_by == "owner"
    created_event = authz.db.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "workflow.created")
    )
    assert created_event is not None
    assert created_event.actor == "owner"

    _seed_run(authz.db, "run-other", created_by="other")
    _seed_run(authz.db, "run-legacy", created_by=None)

    owner_ids = {row["id"] for row in authz.client.get("/workflows").json()}
    assert run_id in owner_ids
    assert "run-other" not in owner_ids
    assert "run-legacy" not in owner_ids
    assert authz.client.get(f"/workflows/{run_id}").status_code == 200

    authz.as_user("other")
    assert authz.client.get(f"/workflows/{run_id}").status_code == 404

    # Current DB role wins even when the token role snapshot says member.
    authz.as_user("admin", claimed_role="member")
    admin_ids = {row["id"] for row in authz.client.get("/workflows").json()}
    assert {run_id, "run-other", "run-legacy"} <= admin_ids
    assert authz.client.get("/workflows/run-legacy").status_code == 200

    # A stale admin claim does not restore access after demotion.
    authz.as_user("demoted", claimed_role="admin")
    assert authz.client.get(f"/workflows/{run_id}").status_code == 404


def test_workflow_approve_and_cancel_require_creator_or_current_admin(authz):
    _seed_run(
        authz.db,
        "run-owner",
        created_by="owner",
        item_ids=("item-approve", "item-cancel", "item-admin"),
    )
    _seed_run(authz.db, "run-legacy", created_by=None, item_ids=("item-legacy",))

    authz.as_user("other")
    assert (
        authz.client.post("/workflows/run-owner/action-items/item-approve/approve").status_code
        == 404
    )
    assert (
        authz.client.post("/workflows/run-owner/action-items/item-cancel/cancel").status_code
        == 404
    )
    assert (
        authz.client.post("/workflows/run-legacy/action-items/item-legacy/approve").status_code
        == 404
    )
    assert authz.db.get(ActionItemRecord, "item-approve").status == "needs_review"
    assert authz.db.get(ActionItemRecord, "item-cancel").status == "needs_review"

    authz.as_user("owner")
    approved = authz.client.post("/workflows/run-owner/action-items/item-approve/approve")
    cancelled = authz.client.post("/workflows/run-owner/action-items/item-cancel/cancel")
    assert approved.status_code == 200
    assert cancelled.status_code == 200
    assert authz.db.get(ActionItemRecord, "item-cancel").status == "cancelled"
    owner_events = authz.db.scalars(
        select(AuditEvent).where(
            AuditEvent.event_type.in_(
                ("action_item.claimed", "action_item.approved", "action_item.cancelled")
            )
        )
    ).all()
    assert owner_events
    assert {event.actor for event in owner_events} == {"owner"}

    authz.as_user("admin", claimed_role="member")
    assert (
        authz.client.post("/workflows/run-legacy/action-items/item-legacy/cancel").status_code
        == 200
    )

    authz.as_user("demoted", claimed_role="admin")
    assert (
        authz.client.post("/workflows/run-owner/action-items/item-admin/cancel").status_code
        == 404
    )


def test_connector_document_listing_applies_acl_tier_and_key_validation(authz):
    _seed_document(authz.db, "doc-company", permissions=["source:all"])
    _seed_document(authz.db, "doc-owner", permissions=["user:owner"])
    _seed_document(authz.db, "doc-other", permissions=["user:other"])
    _seed_document(authz.db, "doc-dept", permissions=["dept:dept-eng"])
    _seed_document(authz.db, "doc-red", permissions=["source:all"], tier="red")

    owner_docs = {
        row["id"]
        for row in authz.client.get("/integrations/upload/documents?limit=500").json()
    }
    assert owner_docs == {"doc-company", "doc-owner", "doc-dept"}

    authz.as_user("other")
    other_docs = {
        row["id"]
        for row in authz.client.get("/integrations/upload/documents?limit=500").json()
    }
    assert other_docs == {"doc-company", "doc-other"}

    authz.as_user("admin", claimed_role="member")
    admin_docs = {
        row["id"]
        for row in authz.client.get("/integrations/upload/documents?limit=500").json()
    }
    assert admin_docs == {"doc-company", "doc-dept", "doc-red"}

    assert authz.client.get("/integrations/not-real/documents").status_code == 404
    assert authz.client.get("/integrations/Bad.Key/documents").status_code == 404

    authz.db.add(ConnectorRecord(key="gmail", display_name="Gmail", capabilities=["sync"]))
    authz.db.add(
        ConnectorAccount(org_id=ORG_ID, connector_key="gmail", auth_state="connected")
    )
    authz.db.commit()
    empty_known = authz.client.get("/integrations/gmail/documents")
    assert empty_known.status_code == 200
    assert empty_known.json() == []


def test_full_document_access_roster_is_uploader_or_current_admin_only(authz):
    _seed_document(
        authz.db,
        "doc-shared",
        permissions=["user:owner", "user:other"],
        author="owner@example.test",
    )
    _seed_document(
        authz.db,
        "doc-legacy",
        permissions=["source:all"],
        author=None,
    )

    owner_view = authz.client.get("/documents/doc-shared/access")
    assert owner_view.status_code == 200
    assert {person["id"] for person in owner_view.json()["people"]} == {"owner", "other"}

    authz.as_user("other")
    assert authz.client.get("/documents/doc-shared/access").status_code == 403
    assert authz.client.get("/documents/doc-legacy/access").status_code == 403

    authz.as_user("admin", claimed_role="member")
    assert authz.client.get("/documents/doc-shared/access").status_code == 200
    assert authz.client.get("/documents/doc-legacy/access").status_code == 200

    authz.as_user("demoted", claimed_role="admin")
    assert authz.client.get("/documents/doc-shared/access").status_code == 403


def test_connector_author_is_never_treated_as_direct_upload_owner(authz):
    authz.db.add(
        SourceDocumentRecord(
            id="connector-doc",
            org_id=ORG_ID,
            source_type="notion",
            external_id="notion-page",
            title="Connector-owned page",
            author="owner@example.test",
            text="private connector content",
            permissions=["user:other"],
            data_tier="normal",
        )
    )
    authz.db.commit()

    assert authz.client.get("/documents/connector-doc/access").status_code == 404
    response = authz.client.patch(
        "/documents/connector-doc/access", json={"visibility": "company"}
    )
    assert response.status_code == 404
    assert authz.db.get(SourceDocumentRecord, "connector-doc").permissions == ["user:other"]


def test_admin_access_update_preserves_the_original_upload_owner(authz, monkeypatch):
    class Store:
        async def set_document_payload(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        "api.routes.documents.get_default_qdrant_store", lambda: Store()
    )
    _seed_document(
        authz.db,
        "owner-upload",
        permissions=["source:all"],
        author="owner@example.test",
    )
    authz.as_user("admin", claimed_role="member")
    response = authz.client.patch(
        "/documents/owner-upload/access", json={"visibility": "personal"}
    )
    assert response.status_code == 200, response.text
    assert authz.db.get(SourceDocumentRecord, "owner-upload").permissions == ["user:owner"]


def test_access_revocation_removes_only_that_documents_share_notice(authz, monkeypatch):
    class Store:
        async def set_document_payload(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        "api.routes.documents.get_default_qdrant_store", lambda: Store()
    )
    _seed_document(
        authz.db,
        "shared-upload",
        permissions=["user:owner", "user:other"],
        author="owner@example.test",
    )
    authz.db.add_all(
        [
            Notification(
                id="revoked-share-notice",
                org_id=ORG_ID,
                user_id="other",
                type="document.shared",
                payload={"document_id": "shared-upload"},
            ),
            Notification(
                id="unrelated-share-notice",
                org_id=ORG_ID,
                user_id="other",
                type="document.shared",
                payload={"document_id": "another-upload"},
            ),
        ]
    )
    authz.db.commit()

    response = authz.client.patch(
        "/documents/shared-upload/access", json={"visibility": "personal"}
    )

    assert response.status_code == 200, response.text
    assert authz.db.get(Notification, "revoked-share-notice") is None
    assert authz.db.get(Notification, "unrelated-share-notice") is not None


def test_action_item_repository_helpers_enforce_parent_workflow_org(authz):
    foreign_org = "foreign-action-org"
    authz.db.add(Org(id=foreign_org, name="Foreign action org"))
    authz.db.add(
        WorkflowRun(
            id="foreign-run",
            org_id=foreign_org,
            created_by=None,
            kind="meeting_action_items",
            status="needs_review",
            input_text="private foreign workflow",
            destination="manual",
            data_tier="normal",
        )
    )
    authz.db.add(
        ActionItemRecord(
            id="foreign-item",
            workflow_run_id="foreign-run",
            title="Foreign action",
            destination="manual",
            status="needs_review",
        )
    )
    authz.db.commit()

    assert claim_action_item(
        authz.db, item_id="foreign-item", org_id=ORG_ID, actor="owner"
    ) == "absent"
    assert cancel_action_item(
        authz.db, item_id="foreign-item", org_id=ORG_ID, actor="owner"
    ) == "absent"
    assert approve_action_item(
        authz.db, item_id="foreign-item", org_id=ORG_ID, actor="owner"
    ) is None
    update_action_item_execution(
        authz.db,
        item_id="foreign-item",
        org_id=ORG_ID,
        status="completed",
    )
    assert authz.db.get(ActionItemRecord, "foreign-item").status == "needs_review"

    assert claim_action_item(
        authz.db, item_id="foreign-item", org_id=foreign_org, actor="foreign-owner"
    ) == "claimed"
    assert approve_action_item(
        authz.db, item_id="foreign-item", org_id=foreign_org, actor="foreign-owner"
    ) is not None
    update_action_item_execution(
        authz.db,
        item_id="foreign-item",
        org_id=foreign_org,
        status="completed",
    )
    events = authz.db.scalars(
        select(AuditEvent).where(
            AuditEvent.payload["item_id"].as_string() == "foreign-item"
        )
    ).all()
    assert events
    assert {event.org_id for event in events} == {foreign_org}
