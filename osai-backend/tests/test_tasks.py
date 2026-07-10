"""Tests for Celery task functions (ingest & extract)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import ActionItemRecord, Automation, Base, SourceDocumentRecord, WorkflowRun, now_utc
from db.repositories import seed_demo_data
from workers.tasks.extract import extract_action_items
from workers.tasks.ingest import MAX_TRANSCRIBE_BYTES, _validate_transcription_size, download_and_transcribe
from workers.tasks.ingest import sync_composio_connections
from workers.tasks.execute import run_due_automations


def test_download_and_transcribe_with_extract_task_chain() -> None:
    # 1. Setup in-memory SQLite DB
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine)

    # Seed orgs & connectors
    with TestSessionLocal() as session:
        seed_demo_data(session)

    # 2. Patch database SessionLocal and Qdrant store to run locally
    with (
        patch("workers.tasks.ingest.SessionLocal", TestSessionLocal),
        patch("workers.tasks.extract.SessionLocal", TestSessionLocal),
        patch("workers.tasks.extract.extract_action_items") as mock_extract_task,
        patch("memory.qdrant_store.get_default_qdrant_store") as mock_qdrant_store,
    ):
        mock_qdrant = MagicMock()

        # mock upsert_chunks to be async
        async def mock_upsert(chunks):
            return len(chunks)

        mock_qdrant.upsert_chunks.side_effect = mock_upsert
        mock_qdrant_store.return_value = mock_qdrant

        # Call download_and_transcribe synchronously
        result = download_and_transcribe(
            meeting_id="meeting-123",
            download_url="http://example.com/audio.m4a",
            topic="Daily Standup",
            org_id="demo-org",
        )

        assert result["status"] == "success"
        run_id = result["workflow_run_id"]
        assert run_id.startswith("workflow-")

        # 3. Check DB records
        with TestSessionLocal() as session:
            # Source document is persisted
            doc = session.get(SourceDocumentRecord, "demo-org:zoom:meeting:meeting-123")
            assert doc is not None
            assert doc.title == "Daily Standup"
            assert "Anish" in doc.text

            # Workflow run is initialized in "processing" state
            run = session.get(WorkflowRun, run_id)
            assert run is not None
            assert run.status == "processing"

        # Verify extract task was enqueued
        mock_extract_task.delay.assert_called_once_with(run_id)


def test_download_and_transcribe_refuses_fixture_for_non_demo_org() -> None:
    with pytest.raises(RuntimeError, match="Transcription is unavailable"):
        download_and_transcribe(
            meeting_id="meeting-real",
            download_url=None,
            topic="Real customer meeting",
            org_id="customer-org",
        )


def test_transcription_rejects_oversized_recording() -> None:
    with pytest.raises(RuntimeError, match="25 MB transcription limit"):
        _validate_transcription_size(b"x" * (MAX_TRANSCRIBE_BYTES + 1))


def test_composio_sync_task_uses_worker_session() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine)

    async def _sync(org_id, session):
        assert org_id == "demo-org"
        assert session is not None
        return {"status": "ok", "synced": []}

    with (
        patch("workers.tasks.ingest.SessionLocal", test_session),
        patch("connectors.composio_ingest.sync_all_connections", _sync),
    ):
        assert sync_composio_connections("demo-org") == {"status": "ok", "synced": []}


def test_extract_action_items_task() -> None:
    # 1. Setup in-memory SQLite DB
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine)

    # Seed orgs & connectors
    with TestSessionLocal() as session:
        seed_demo_data(session)
        # Create a pre-existing workflow run in "processing" state
        session.add(
            WorkflowRun(
                id="workflow-abc",
                org_id="demo-org",
                kind="meeting_action_items",
                status="processing",
                input_text="Anish: I will write the Zoom webhook endpoint by next Tuesday.",
                destination="manual",
                data_tier="normal",
                model_route="whisper-1",
            )
        )
        session.commit()

    # 2. Patch session and execute extraction task
    with (
        patch("workers.tasks.extract.SessionLocal", TestSessionLocal),
        patch("workers.tasks.extract.run_action_item_workflow") as mock_workflow_runner,
    ):
        from api.schemas.workflow_run import ActionItem, WorkflowRunResponse

        # mock workflow extraction response
        mock_workflow_runner.return_value = WorkflowRunResponse(
            id="workflow-abc",
            status="needs_review",
            model_route="gemini-2.0-flash",
            action_items=[
                ActionItem(
                    title="Write the Zoom webhook endpoint",
                    owner="Anish",
                    due_date="2026-06-09",
                    source_quote="Anish: I will write the Zoom webhook endpoint by next Tuesday.",
                    destination="manual",
                    confidence=0.9,
                )
            ],
            audit_event_ids=["audit-1"],
        )

        result = extract_action_items("workflow-abc")
        assert result["status"] == "success"

        # 3. Check run status update and action item persistence in DB
        with TestSessionLocal() as session:
            run = session.get(WorkflowRun, "workflow-abc")
            assert run.status == "needs_review"
            assert run.model_route == "gemini-2.0-flash"

            action_items = (
                session.query(ActionItemRecord)
                .filter(ActionItemRecord.workflow_run_id == "workflow-abc")
                .all()
            )
            assert len(action_items) == 1
            item = action_items[0]
            assert item.title == "Write the Zoom webhook endpoint"
            assert item.owner == "Anish"
            assert item.confidence == 0.9
            assert item.status == "needs_review"


def test_due_automations_skip_manual_and_paused_rows() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine)
    with TestSessionLocal() as session:
        session.add_all(
            [
                Automation(id="due", org_id="demo-org", name="Due", prompt="run", cadence="hourly"),
                Automation(id="manual", org_id="demo-org", name="Manual", prompt="run", cadence="manual"),
                Automation(id="paused", org_id="demo-org", name="Paused", prompt="run", cadence="hourly", status="paused"),
                Automation(id="fresh", org_id="demo-org", name="Fresh", prompt="run", cadence="daily", last_run_at=now_utc() - timedelta(hours=1)),
            ]
        )
        session.commit()
    with (
        patch("workers.tasks.execute.SessionLocal", TestSessionLocal),
        patch("workers.tasks.execute.run_automation", new_callable=AsyncMock) as runner,
    ):
        result = run_due_automations()
    assert result == {"ran": 1, "failed": 0}
    assert runner.await_args.args[0] == "due"
