"""Workflow-enrichment ACL regression tests (audit High #3).

Enrichment context is injected into the extraction prompt, so it must be
filtered by the initiating user's permission grants and clearance tier — the
same governance rule as retrieval. System context (no initiating user) keeps
see-all behaviour for webhook/Celery-triggered runs.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import ActionItemRecord, Base, SourceDocumentRecord, WorkflowRun
from workflows.enricher import get_workflow_context


def _hit(title: str, permissions: list[str] | None, tier: str = "normal"):
    hit = MagicMock()
    hit.score = 0.9
    hit.payload = {
        "source_document_id": f"doc-{title}",
        "title": title,
        "text": f"{title} contents",
        "source_type": "notion",
        "url": None,
        "permissions": permissions,
        "data_tier": tier,
    }
    return hit


_HITS = [
    _hit("public-doc", permissions=["source:all"]),
    _hit("slack-doc", permissions=["source:slack"]),
    _hit("red-doc", permissions=["source:all"], tier="red"),
]


def _context(requester_permissions=None, requester_tier="red"):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with (
        patch("workflows.enricher.get_default_qdrant_store") as mock_store,
        patch("workflows.enricher.default_embedding_provider") as mock_emb,
    ):
        mock_qdrant = MagicMock()

        async def mock_search(*args, **kwargs):
            return list(_HITS)

        mock_qdrant.search.side_effect = mock_search
        mock_store.return_value = mock_qdrant

        async def mock_embed(*args, **kwargs):
            return [[0.1] * 768]

        mock_emb.embed_texts.side_effect = mock_embed

        with session_factory() as session:
            for hit in _HITS:
                payload = hit.payload
                session.add(
                    SourceDocumentRecord(
                        id=payload["source_document_id"],
                        org_id="demo-org",
                        source_type=payload["source_type"],
                        external_id=payload["source_document_id"],
                        title=payload["title"],
                        text=payload["text"],
                        permissions=payload["permissions"],
                        data_tier=payload["data_tier"],
                    )
                )
            session.commit()
            return get_workflow_context(
                org_id="demo-org",
                query_text="anything",
                session=session,
                requester_permissions=requester_permissions,
                requester_tier=requester_tier,
            )


def _titles(context) -> set[str]:
    return {d["title"] for d in context["documents"]}


def test_member_enrichment_filtered_by_grants_and_tier():
    ctx = _context(requester_permissions=["source:notion"], requester_tier="normal")
    assert _titles(ctx) == {"public-doc"}


def test_member_with_grant_sees_matching_doc():
    ctx = _context(requester_permissions=["source:slack"], requester_tier="amber")
    assert _titles(ctx) == {"public-doc", "slack-doc"}


def test_system_context_keeps_see_all():
    ctx = _context()  # defaults: no initiating user → see-all
    assert _titles(ctx) == {"public-doc", "slack-doc", "red-doc"}
    assert {doc["title"]: doc["data_tier"] for doc in ctx["documents"]} == {
        "public-doc": "normal",
        "slack-doc": "normal",
        "red-doc": "red",
    }


def test_red_doc_withheld_below_red_clearance():
    ctx = _context(requester_permissions=["role:admin"], requester_tier="amber")
    assert "red-doc" not in _titles(ctx)


def test_recent_action_items_are_scoped_to_creator_or_current_admin():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        session.add_all(
            [
                WorkflowRun(
                    id="run-alice",
                    org_id="demo-org",
                    created_by="alice",
                    kind="meeting_action_items",
                    status="needs_review",
                    input_text="Alice's private transcript",
                    destination="manual",
                    data_tier="normal",
                ),
                WorkflowRun(
                    id="run-bob",
                    org_id="demo-org",
                    created_by="bob",
                    kind="meeting_action_items",
                    status="needs_review",
                    input_text="Bob's private transcript",
                    destination="manual",
                    data_tier="normal",
                ),
                WorkflowRun(
                    id="run-legacy",
                    org_id="demo-org",
                    created_by=None,
                    kind="meeting_action_items",
                    status="needs_review",
                    input_text="Legacy transcript",
                    destination="manual",
                    data_tier="normal",
                ),
                ActionItemRecord(
                    id="item-alice",
                    workflow_run_id="run-alice",
                    title="Alice only",
                ),
                ActionItemRecord(
                    id="item-bob",
                    workflow_run_id="run-bob",
                    title="Bob only",
                ),
                ActionItemRecord(
                    id="item-legacy",
                    workflow_run_id="run-legacy",
                    title="Legacy admin only",
                ),
            ]
        )
        session.commit()

        alice = get_workflow_context(
            "demo-org", "", session, actor_user_id="alice"
        )
        bob = get_workflow_context("demo-org", "", session, actor_user_id="bob")
        system = get_workflow_context("demo-org", "", session)
        admin = get_workflow_context(
            "demo-org", "", session, actor_user_id="admin", viewer_is_admin=True
        )

    assert {item["title"] for item in alice["action_items"]} == {"Alice only"}
    assert {item["title"] for item in bob["action_items"]} == {"Bob only"}
    assert system["action_items"] == []
    assert {item["title"] for item in admin["action_items"]} == {
        "Alice only",
        "Bob only",
        "Legacy admin only",
    }
