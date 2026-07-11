"""Department-scoped retrieval ("Ask Engineering")."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from api.schemas.connector import SourceDocument
from api.schemas.search import SearchRequest
from memory.chunker import chunk_document
from memory.qdrant_store import _chunk_payload
from memory.retriever import retrieve_answer


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_chunk_and_payload_carry_department():
    doc = SourceDocument(
        source_id="s1",
        source_type="upload",
        org_id="org-1",
        external_id="s1",
        title="Eng runbook",
        text="restart the worker",
        department_id="dept-eng",
    )
    chunk = chunk_document(doc)[0]
    assert chunk["department_id"] == "dept-eng"
    assert _chunk_payload(chunk)["department_id"] == "dept-eng"


def _hit(title: str, dept: str | None):
    hit = MagicMock()
    hit.score = 0.95
    hit.payload = {
        "title": title,
        "text": "content",
        "source_type": "upload",
        "url": None,
        "source_document_id": f"doc-{title}",
        "data_tier": "normal",
        "permissions": ["source:all"],
        "department_id": dept,
    }
    return hit


@pytest.mark.anyio
async def test_department_filter_narrows_retrieval():
    hits = [_hit("eng-doc", "dept-eng"), _hit("hr-doc", "dept-hr"), _hit("org-doc", None)]
    qdrant = MagicMock()

    async def _search(*a, **k):
        return list(hits)

    qdrant.search.side_effect = _search
    emb = MagicMock()

    async def _embed(*a, **k):
        return [[0.1] * 768]

    emb.embed_texts.side_effect = _embed

    async def _ask(department_id):
        with (
            patch("memory.retriever.get_default_qdrant_store", return_value=qdrant),
            patch("memory.retriever.default_embedding_provider", emb),
            patch("memory.org_memory.fetch_relevant", return_value=[]),
        ):
            return await retrieve_answer(
                SearchRequest(
                    org_id="org-1", query="anything", department_id=department_id
                )
            )

    scoped = await _ask("dept-eng")
    assert [c.source_record_title for c in scoped.citations] == ["eng-doc"]

    unscoped = await _ask(None)
    assert {c.source_record_title for c in unscoped.citations} == {
        "eng-doc",
        "hr-doc",
        "org-doc",
    }
