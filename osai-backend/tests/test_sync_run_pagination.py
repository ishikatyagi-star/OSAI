from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.main import app
from db.models import Base, Org, SyncRun
from db.session import get_db


@pytest.fixture
def sync_client():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([Org(id="demo-org", name="QA"), Org(id="other-org", name="Other")])
    base = datetime(2026, 7, 21, tzinfo=UTC)
    rows = [
        ("run-5", "notion", "succeeded", 7, 6),
        ("run-4", "slack", "failed", 5, 0),
        ("run-3", "notion", "running", 2, 1),
        ("run-2", "slack", "succeeded", 4, 4),
        ("run-1", "notion", "succeeded", 3, 3),
    ]
    session.add_all(
        SyncRun(
            id=run_id,
            org_id="demo-org",
            connector_key=connector,
            status=status,
            documents_seen=seen,
            documents_indexed=indexed,
            started_at=base + timedelta(minutes=index),
        )
        for index, (run_id, connector, status, seen, indexed) in enumerate(rows)
    )
    session.add(
        SyncRun(
            id="other-run",
            org_id="other-org",
            connector_key="notion",
            status="failed",
            documents_seen=99,
            documents_indexed=99,
            started_at=base + timedelta(days=1),
        )
    )
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()


def test_cursor_pages_keep_all_time_totals_and_tenant_scope(sync_client: TestClient):
    first = sync_client.get("/sync-runs/page?limit=2")
    assert first.status_code == 200
    page = first.json()
    assert [row["id"] for row in page["items"]] == ["run-1", "run-2"]
    assert page["next_cursor"] == "run-2"
    assert page["summary"] == {
        "total_runs": 5,
        "status_counts": {"failed": 1, "running": 1, "succeeded": 3},
        "documents_seen": 21,
        "documents_indexed": 14,
        "by_connector": {
            "notion": {
                "total_runs": 3,
                "status_counts": {"running": 1, "succeeded": 2},
                "documents_seen": 12,
                "documents_indexed": 10,
            },
            "slack": {
                "total_runs": 2,
                "status_counts": {"failed": 1, "succeeded": 1},
                "documents_seen": 9,
                "documents_indexed": 4,
            },
        },
    }
    assert page["as_of"]

    second = sync_client.get(f"/sync-runs/page?limit=2&cursor={page['next_cursor']}").json()
    assert [row["id"] for row in second["items"]] == ["run-3", "run-4"]
    assert second["next_cursor"] == "run-4"
    third = sync_client.get(
        f"/sync-runs/page?limit=2&cursor={second['next_cursor']}"
    ).json()
    assert [row["id"] for row in third["items"]] == ["run-5"]
    assert third["next_cursor"] is None
    assert third["summary"] == page["summary"]


def test_cursor_must_belong_to_the_current_org(sync_client: TestClient):
    response = sync_client.get("/sync-runs/page?cursor=other-run")
    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid sync-run cursor."
