"""Tests for Celery task functions (ingest & extract)."""

from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import ActionItemRecord, Base, WorkflowRun
from db.repositories import seed_demo_data
from workers.tasks.extract import extract_action_items


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
        call = mock_workflow_runner.call_args.kwargs
        assert call["actor_user_id"] is None
        assert call["viewer_is_admin"] is False

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
