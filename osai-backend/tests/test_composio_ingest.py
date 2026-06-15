"""Composio OAuth-based ingestion (Notion) — structural test with a mocked client."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from connectors.composio_ingest import ingest_composio_toolkit
from db.models import Base, SourceDocumentRecord


class _FakeComposio:
    def available(self):
        return True

    async def execute(self, slug, arguments, user_id):
        if slug == "NOTION_SEARCH_NOTION_PAGE":
            return {
                "data": {
                    "response_data": {
                        "results": [
                            {
                                "id": "page-1",
                                "url": "https://notion.so/page-1",
                                "properties": {
                                    "Name": {
                                        "type": "title",
                                        "title": [{"plain_text": "Onboarding Guide"}],
                                    }
                                },
                            }
                        ]
                    }
                }
            }
        if slug == "NOTION_FETCH_BLOCK_CONTENTS":
            return {
                "data": {
                    "response_data": {
                        "results": [
                            {
                                "type": "paragraph",
                                "paragraph": {
                                    "rich_text": [{"plain_text": "Welcome to the team."}]
                                },
                            }
                        ]
                    }
                }
            }
        return {"successful": False, "data": None, "error": "unknown"}


class _FakeQdrant:
    async def upsert_chunks(self, chunks):
        return len(chunks)


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


async def test_notion_ingestion_indexes_documents():
    session = _session()
    result = await ingest_composio_toolkit(
        "demo-org", "notion", session, client=_FakeComposio(), qdrant_store=_FakeQdrant()
    )
    assert result["status"] == "succeeded"
    assert result["documents_indexed"] == 1

    rows = session.query(SourceDocumentRecord).all()
    assert len(rows) == 1
    doc = rows[0]
    assert doc.source_type == "notion"
    assert doc.title == "Onboarding Guide"
    assert "Welcome to the team" in doc.text


async def test_unsupported_toolkit_is_rejected():
    session = _session()
    result = await ingest_composio_toolkit(
        "demo-org", "salesforce", session, client=_FakeComposio(), qdrant_store=_FakeQdrant()
    )
    assert result["status"] == "failed"
    assert "not implemented" in result["error"].lower()
