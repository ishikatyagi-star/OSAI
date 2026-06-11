"""Tests for context enrichment (Qdrant chunks & Postgres recent action items)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import ActionItemRecord, Base, WorkflowRun
from db.repositories import seed_demo_data
from workflows.enricher import get_workflow_context
from workflows.prompts.action_items import build_extraction_prompt
from workflows.runner import run_action_item_workflow


def test_get_workflow_context_db_retrieval() -> None:
    # 1. Setup in-memory SQLite DB
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine)

    # Seed orgs
    with TestSessionLocal() as session:
        seed_demo_data(session)
        # Create a workflow run and associated action items
        session.add(
            WorkflowRun(
                id="run-1",
                org_id="demo-org",
                kind="meeting_action_items",
                status="completed",
                input_text="Sample raw transcript",
                destination="manual",
                data_tier="normal",
            )
        )
        session.add(
            ActionItemRecord(
                id="item-1",
                workflow_run_id="run-1",
                title="Write documentation",
                owner="Ishika",
                confidence=0.85,
                status="needs_review",
            )
        )
        session.commit()

    # 2. Patch Qdrant and default_embedding_provider to mock search results
    with (
        patch("workflows.enricher.get_default_qdrant_store") as mock_qdrant_store,
        patch("workflows.enricher.default_embedding_provider") as mock_emb_provider,
    ):
        mock_qdrant = MagicMock()
        mock_hit = MagicMock()
        mock_hit.score = 0.92
        mock_hit.payload = {
            "title": "OSAI Project Plan",
            "text": "The main goal is to ship Zoom, Notion, and Slack connections.",
            "source_type": "notion",
            "url": "http://notion.so/osai",
        }

        # Mock search method
        async def mock_search(*args, **kwargs):
            return [mock_hit]

        mock_qdrant.search.side_effect = mock_search
        mock_qdrant_store.return_value = mock_qdrant

        # Mock embed_texts method
        async def mock_embed(*args, **kwargs):
            return [[0.1] * 768]

        mock_emb_provider.embed_texts.side_effect = mock_embed

        with TestSessionLocal() as session:
            context = get_workflow_context(
                org_id="demo-org",
                query_text="documentation",
                session=session,
            )

            # Assert Qdrant search parsed correctly
            assert len(context["documents"]) == 1
            doc = context["documents"][0]
            assert doc["title"] == "OSAI Project Plan"
            assert doc["source_type"] == "notion"
            assert doc["confidence"] == 0.92

            # Assert DB action items fetched correctly via join
            assert len(context["action_items"]) == 1
            item = context["action_items"][0]
            assert item["title"] == "Write documentation"
            assert item["owner"] == "Ishika"
            assert item["status"] == "needs_review"


def test_build_extraction_prompt_formatting() -> None:
    context_docs = [
        {
            "title": "Notion Integration Design",
            "text": "Notion uses oauth keys.",
            "source_type": "notion",
        }
    ]
    existing_items = [
        {
            "title": "Fix notion auth",
            "owner": "anish@osai.local",
            "status": "needs_review",
        }
    ]

    prompt = build_extraction_prompt(
        input_text="Yash: We need to fix notion auth.",
        destination="notion",
        context_documents=context_docs,
        existing_action_items=existing_items,
    )

    # Verify context content is formatted in the prompt
    assert "### RELATED ORG CONTEXT:" in prompt
    assert "[NOTION] Notion Integration Design" in prompt
    assert "Notion uses oauth keys." in prompt
    assert "### RECENT ACTION ITEMS" in prompt
    assert "- Fix notion auth (Assignee: anish@osai.local, Status: needs_review)" in prompt
    assert "Default destination for extracted items: notion" in prompt


@patch("workflows.runner.run_action_item_workflow")
def test_workflows_runner_with_empty_context_fallback(mock_runner) -> None:
    # Test that runner executes successfully even if DB session is None or Qdrant fails
    mock_runner.return_value = MagicMock()
    from api.schemas.workflow_run import WorkflowRunCreate

    req = WorkflowRunCreate(
        org_id="demo-org",
        input_text="Simple task text",
        destination="manual",
        data_tier="normal",
    )
    asyncio.run(run_action_item_workflow(run_id="run-1", request=req, db=None))
