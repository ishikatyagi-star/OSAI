"""Postgres remains authoritative when Qdrant document metadata is stale."""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.schemas.search import SearchRequest
from config import settings
from db.models import Base, SourceDocumentRecord
from llm.policy import DEFAULT_DATA_ROUTING


async def test_retrieval_revalidates_stale_qdrant_grants_against_postgres(monkeypatch):
    import memory.org_memory as org_memory
    import memory.retriever as retriever

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        upload = SourceDocumentRecord(
            id="upload-private",
            org_id="org-1",
            source_type="upload",
            external_id="upload-private",
            title="Private upload",
            text="private upload content",
            permissions=["source:all"],
            data_tier="normal",
        )
        connector = SourceDocumentRecord(
            id="notion-page",
            org_id="org-1",
            source_type="notion",
            external_id="page-1",
            title="Current connector title",
            text="connector content",
            permissions=["source:notion"],
            data_tier="normal",
        )
        session.add_all([upload, connector])
        session.commit()

        # Postgres revokes company-wide access. The failed Qdrant payload update
        # leaves the broader grant and old metadata on the vector hit.
        upload.permissions = ["user:owner"]
        session.commit()

    hits = [
        SimpleNamespace(
            score=0.99,
            payload={
                "source_document_id": "upload-private",
                "source_type": "upload",
                "title": "Stale public upload",
                "text": "private upload content",
                "permissions": ["source:all"],
                "data_tier": "normal",
            },
        ),
        SimpleNamespace(
            score=0.85,
            payload={
                "source_document_id": "notion-page",
                "source_type": "notion",
                "title": "Stale connector title",
                "text": "connector content",
                "permissions": ["source:notion"],
                "data_tier": "normal",
            },
        ),
    ]

    class Store:
        async def search(self, *_args, **_kwargs):
            return hits

    class Embeddings:
        async def embed_texts(self, _texts):
            return [[0.0] * 8]

    monkeypatch.setattr(retriever, "SessionLocal", session_factory, raising=False)
    monkeypatch.setattr(retriever, "get_default_qdrant_store", lambda: Store())
    monkeypatch.setattr(retriever, "default_embedding_provider", Embeddings())
    monkeypatch.setattr(retriever, "load_data_routing", lambda _org_id: DEFAULT_DATA_ROUTING)
    monkeypatch.setattr(org_memory, "fetch_relevant", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")

    response = await retriever.retrieve_answer(
        SearchRequest(
            org_id="org-1",
            query="content",
            requester_permissions=["source:notion", "user:revoked"],
            requester_tier="normal",
        )
    )

    assert [citation.source_record_title for citation in response.citations] == [
        "Current connector title"
    ]

    engine.dispose()
