"""Saved artifacts CRUD."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from api.main import app
from db.models import Base, Org, SavedArtifact, User
from db.session import (
    get_db,
    get_optional_claims,
    get_org_id,
    require_writable_org,
)


def _artifact_data(*, artifact_id: str = "qa-artifact", title: str = "QA artifact") -> dict:
    return {
        "id": artifact_id,
        "kind": "source_table",
        "title": title,
        "rows": [{"label": "T-1", "value": "open"}],
    }


@dataclass
class ArtifactContext:
    client: TestClient
    db: Session
    state: dict[str, Any]


@pytest.fixture
def artifacts() -> ArtifactContext:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.add(Org(id="demo-org", name="Artifact QA"))
    session.add(
        User(
            id="artifact-demo-admin",
            org_id="demo-org",
            email="artifact-admin@example.test",
            display_name="Artifact admin",
            role="admin",
        )
    )
    session.commit()

    state: dict[str, Any] = {
        "org_id": "demo-org",
        "claims": {
            "sub": "artifact-demo-admin",
            "email": "artifact-admin@example.test",
            "org_id": "demo-org",
        },
    }
    overrides = {
        get_db: lambda: session,
        get_org_id: lambda: state["org_id"],
        require_writable_org: lambda: state["org_id"],
        get_optional_claims: lambda: state["claims"],
    }
    missing = object()
    previous = {
        dependency: app.dependency_overrides.get(dependency, missing) for dependency in overrides
    }
    app.dependency_overrides.update(overrides)
    client = TestClient(app)
    try:
        yield ArtifactContext(client, session, state)
    finally:
        client.close()
        for dependency, old in previous.items():
            if old is missing:
                app.dependency_overrides.pop(dependency, None)
            else:
                app.dependency_overrides[dependency] = old
        session.close()
        engine.dispose()


def test_save_list_delete_roundtrip(artifacts: ArtifactContext):
    a = artifacts.client.post(
        "/artifacts",
        json={
            "title": "Open SLA escalations",
            "kind": "source_table",
            "data": _artifact_data(),
            "thread_id": None,
        },
    ).json()
    assert a["title"] == "Open SLA escalations"
    assert a["created_at"].endswith("Z")
    assert any(x["id"] == a["id"] for x in artifacts.client.get("/artifacts").json())
    assert artifacts.client.delete(f"/artifacts/{a['id']}").json()["deleted"] is True
    assert artifacts.client.delete(f"/artifacts/{a['id']}").json()["deleted"] is True


def test_artifacts_are_creator_private_and_current_admin_visible(
    artifacts: ArtifactContext,
):
    marker = uuid4().hex
    creator_id = f"artifact-creator-{marker}"
    member_id = f"artifact-member-{marker}"
    admin_id = f"artifact-admin-{marker}"
    artifacts.db.add_all(
        [
            User(
                id=user_id,
                org_id="demo-org",
                email=f"{user_id}@test.local",
                display_name=user_id,
                role=role,
            )
            for user_id, role in (
                (creator_id, "member"),
                (member_id, "member"),
                (admin_id, "admin"),
            )
        ]
    )
    artifacts.db.commit()

    artifacts.state["claims"] = {"sub": creator_id, "org_id": "demo-org"}
    created = artifacts.client.post(
        "/artifacts",
        json={
            "title": "Private SQL rows",
            "kind": "source_table",
            "data": _artifact_data(title="Private SQL rows"),
        },
    )
    assert created.status_code == 200
    artifact_id = created.json()["id"]

    artifacts.state["claims"] = {"sub": member_id, "org_id": "demo-org", "role": "member"}
    assert artifact_id not in {row["id"] for row in artifacts.client.get("/artifacts").json()}
    assert artifacts.client.delete(f"/artifacts/{artifact_id}").status_code == 200

    artifacts.state["claims"] = {"sub": creator_id, "org_id": "demo-org", "role": "member"}
    assert artifact_id in {row["id"] for row in artifacts.client.get("/artifacts").json()}

    legacy = SavedArtifact(org_id="demo-org", title="Legacy ownerless artifact", data={})
    artifacts.db.add(legacy)
    artifacts.db.commit()

    artifacts.state["claims"] = {"sub": admin_id, "org_id": "demo-org", "role": "admin"}
    visible_to_admin = {row["id"] for row in artifacts.client.get("/artifacts").json()}
    assert {artifact_id, legacy.id} <= visible_to_admin

    admin = artifacts.db.get(User, admin_id)
    assert admin is not None
    admin.role = "member"
    artifacts.db.commit()
    visible_after_demotion = {row["id"] for row in artifacts.client.get("/artifacts").json()}
    assert artifact_id not in visible_after_demotion
    assert legacy.id not in visible_after_demotion

    admin.role = "admin"
    artifacts.db.commit()
    assert artifacts.client.delete(f"/artifacts/{artifact_id}").status_code == 200
    assert artifacts.client.delete(f"/artifacts/{artifact_id}").status_code == 200


def test_artifact_payload_is_validated_before_storage(artifacts: ArtifactContext):
    response = artifacts.client.post(
        "/artifacts",
        json={
            "title": "Malformed artifact",
            "kind": "source_table",
            "data": {
                "id": "malformed",
                "kind": "source_table",
                "title": "Malformed artifact",
                "rows": "not-a-list",
            },
        },
    )
    assert response.status_code == 422


def test_artifact_pages_reach_every_row_with_tied_timestamps(
    artifacts: ArtifactContext,
):
    marker = uuid4().hex
    org_id = f"artifact-page-org-{marker}"
    user_id = f"artifact-page-user-{marker}"
    outsider_id = f"artifact-page-outsider-{marker}"
    artifact_ids = [f"artifact-page-{marker}-{index:03d}" for index in range(201)]
    outsider_artifact_id = f"artifact-page-{marker}-outsider"
    created_at = datetime(2099, 1, 1, tzinfo=UTC)

    artifacts.db.add(Org(id=org_id, name="Artifact pagination QA"))
    artifacts.db.add_all(
        [
            User(
                id=user_id,
                org_id=org_id,
                email=f"{user_id}@test.local",
                display_name="Artifact owner",
                role="member",
            ),
            User(
                id=outsider_id,
                org_id=org_id,
                email=f"{outsider_id}@test.local",
                display_name="Other owner",
                role="member",
            ),
        ]
    )
    artifacts.db.add_all(
        SavedArtifact(
            id=artifact_id,
            org_id=org_id,
            title=artifact_id,
            kind="source_table",
            data=_artifact_data(artifact_id=artifact_id, title=artifact_id),
            created_by=user_id,
            created_at=created_at,
        )
        for artifact_id in artifact_ids
    )
    artifacts.db.add(
        SavedArtifact(
            id=outsider_artifact_id,
            org_id=org_id,
            title="Other owner's artifact",
            kind="source_table",
            data=_artifact_data(artifact_id=outsider_artifact_id),
            created_by=outsider_id,
            created_at=created_at,
        )
    )
    artifacts.db.commit()

    artifacts.state["org_id"] = org_id
    artifacts.state["claims"] = {
        "sub": user_id,
        "org_id": org_id,
    }
    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        response = artifacts.client.get("/artifacts/page", params=params)
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 201
        seen.extend(row["id"] for row in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert seen == sorted(artifact_ids, reverse=True)
    invalid = artifacts.client.get("/artifacts/page", params={"cursor": outsider_artifact_id})
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "Invalid artifact cursor."
