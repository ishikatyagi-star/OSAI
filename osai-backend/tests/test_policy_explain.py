"""Policy-explain on citations: access_reason / model_routing mirror the real
governance decisions (_visible + cloud_llm_allowed), never a separate story."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from api.schemas.search import SearchRequest
from memory.retriever import _access_reason, retrieve_answer


@pytest.fixture
def anyio_backend():
    return "asyncio"


# --- reason helper mirrors _visible branches ---------------------------------


def test_reason_for_system_context():
    assert "System context" in _access_reason(["source:slack"], [])


def test_reason_for_admin():
    assert "admin" in _access_reason(["source:slack"], ["role:admin"])


def test_reason_for_public_doc():
    assert "everyone" in _access_reason(["source:all"], ["source:notion"])
    assert "everyone" in _access_reason(None, ["source:notion"])


def test_reason_names_the_matching_grant():
    reason = _access_reason(["source:slack", "source:hr"], ["source:slack"])
    assert "source:slack" in reason


# --- retrieval carries explain fields ----------------------------------------


def _hit(title: str, tier: str, permissions: list[str]):
    hit = MagicMock()
    hit.score = 0.95
    hit.payload = {
        "title": title,
        "text": "content",
        "source_type": "notion",
        "url": None,
        "source_document_id": f"doc-{title}",
        "data_tier": tier,
        "permissions": permissions,
    }
    return hit


@pytest.mark.anyio
async def test_citations_carry_access_and_routing_explanations():
    hits = [
        _hit("open-doc", "normal", ["source:all"]),
        _hit("red-doc", "red", ["source:all"]),
    ]
    qdrant = MagicMock()

    async def _search(*a, **k):
        return hits

    qdrant.search.side_effect = _search

    async def _embed(*a, **k):
        return [[0.1] * 768]

    emb = MagicMock()
    emb.embed_texts.side_effect = _embed

    with (
        patch("memory.retriever.get_default_qdrant_store", return_value=qdrant),
        patch("memory.retriever.default_embedding_provider", emb),
        patch("memory.org_memory.fetch_relevant", return_value=[]),
        # Default routing policy: red never goes to cloud.
    ):
        resp = await retrieve_answer(
            SearchRequest(
                org_id="demo-org",
                query="anything",
                requester_permissions=["source:notion"],
                requester_tier="red",
            )
        )

    by_title = {c.source_record_title: c for c in resp.citations}
    open_doc = by_title["open-doc"]
    assert open_doc.access_reason == "Shared with everyone in your workspace"
    assert open_doc.model_routing == "cloud"
    assert "may be sent to cloud" in open_doc.routing_reason

    red_doc = by_title["red-doc"]
    assert red_doc.model_routing == "local-only"
    assert "restricted to local models" in red_doc.routing_reason
