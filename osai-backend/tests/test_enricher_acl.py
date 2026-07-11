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

from db.models import Base
from workflows.enricher import get_workflow_context


def _hit(title: str, permissions: list[str] | None, tier: str = "normal"):
    hit = MagicMock()
    hit.score = 0.9
    hit.payload = {
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


def test_red_doc_withheld_below_red_clearance():
    ctx = _context(requester_permissions=["role:admin"], requester_tier="amber")
    assert "red-doc" not in _titles(ctx)
