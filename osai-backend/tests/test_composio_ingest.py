"""Composio OAuth-based ingestion (Notion) — structural test with a mocked client."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from connectors.composio_ingest import ingest_composio_toolkit
from db.models import Base, ConnectorAccount, SourceDocumentRecord


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


async def test_notion_ingestion_applies_configured_tier_rules():
    """A tier rule set on the connector account must classify Composio-ingested
    docs the same way the native connector sync path does (regression for the
    gap where Composio ingest silently left everything at the default tier)."""
    session = _session()
    session.add(
        ConnectorAccount(
            org_id="demo-org",
            connector_key="notion",
            tier_rules=[{"pattern": "onboarding", "tier": "amber"}],
        )
    )
    session.commit()

    await ingest_composio_toolkit(
        "demo-org", "notion", session, client=_FakeComposio(), qdrant_store=_FakeQdrant()
    )

    doc = session.query(SourceDocumentRecord).one()
    assert doc.data_tier == "amber"


async def test_unsupported_toolkit_is_rejected():
    session = _session()
    result = await ingest_composio_toolkit(
        "demo-org", "salesforce", session, client=_FakeComposio(), qdrant_store=_FakeQdrant()
    )
    assert result["status"] == "failed"
    assert "not implemented" in result["error"].lower()


class _FakeComposioWithConnections(_FakeComposio):
    async def list_connections(self, user_id):
        # one supported (notion), one unsupported (salesforce), one inactive
        return [
            {"id": "ca_1", "toolkit": "notion", "status": "ACTIVE"},
            {"id": "ca_2", "toolkit": "salesforce", "status": "ACTIVE"},
            {"id": "ca_3", "toolkit": "slack", "status": "INITIATED"},
        ]


async def test_sync_all_only_ingests_active_supported_connections():
    from connectors.composio_ingest import sync_all_connections

    session = _session()
    result = await sync_all_connections(
        "demo-org", session, client=_FakeComposioWithConnections(), qdrant_store=_FakeQdrant()
    )
    assert result["status"] == "ok"
    # Only the active, supported (notion) connection should have been ingested.
    assert len(result["synced"]) == 1
    assert result["synced"][0]["toolkit"] == "notion"


class _FakeComposioGmail(_FakeComposio):
    async def execute(self, slug, arguments, user_id):
        if slug == "GMAIL_FETCH_EMAILS":
            return {
                "data": {
                    "response_data": {
                        "messages": [
                            {
                                "messageId": "msg-1",
                                "subject": "Q3 pricing proposal",
                                "sender": "jane@example.com",
                                "messageText": "Attached is the updated pricing sheet.",
                            },
                            {"messageId": "msg-2", "sender": "bob@example.com"},
                        ]
                    }
                }
            }
        return {"successful": False, "data": None, "error": "unknown"}


async def test_gmail_ingestion_indexes_messages():
    session = _session()
    result = await ingest_composio_toolkit(
        "demo-org", "gmail", session, client=_FakeComposioGmail(), qdrant_store=_FakeQdrant()
    )
    assert result["status"] == "succeeded"
    assert result["documents_indexed"] == 2

    rows = {r.external_id: r for r in session.query(SourceDocumentRecord).all()}
    doc = rows["msg-1"]
    assert doc.source_type == "gmail"
    assert doc.title == "Q3 pricing proposal"
    assert "jane@example.com" in doc.text
    assert "updated pricing sheet" in doc.text
    # A message with no subject/body still indexes under a placeholder title.
    assert rows["msg-2"].title == "(no subject)"


class _CountingQdrant:
    """Counts embed calls so we can assert unchanged docs are not re-embedded."""

    def __init__(self):
        self.embed_calls = 0

    async def upsert_chunks(self, chunks):
        self.embed_calls += 1
        return len(chunks)

    async def delete_document(self, *a, **k):
        return None


async def test_unchanged_documents_are_not_re_embedded_on_resync():
    session = _session()
    q = _CountingQdrant()

    first = await ingest_composio_toolkit(
        "demo-org", "notion", session, client=_FakeComposio(), qdrant_store=q
    )
    assert first["documents_embedded"] == 1
    assert first["documents_skipped_unchanged"] == 0
    assert q.embed_calls == 1

    # Second sync of identical content must skip embedding entirely.
    second = await ingest_composio_toolkit(
        "demo-org", "notion", session, client=_FakeComposio(), qdrant_store=q
    )
    assert second["documents_embedded"] == 0
    assert second["documents_skipped_unchanged"] == 1
    assert q.embed_calls == 1  # unchanged: no new embed call


async def test_failed_ingest_records_a_visible_sync_run():
    """A mid-ingest failure must still leave a failed SyncRun, so /sync-runs never
    shows silence after the user clicked Sync (regression)."""
    from db.models import SyncRun

    session = _session()

    # Force a hard failure *after* fetch by monkeypatching upsert to raise.
    import connectors.composio_ingest as ing

    orig = ing.upsert_source_documents
    ing.upsert_source_documents = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db boom"))
    try:
        result = await ingest_composio_toolkit(
            "demo-org", "notion", session, client=_FakeComposio(), qdrant_store=_FakeQdrant()
        )
    finally:
        ing.upsert_source_documents = orig

    assert result["status"] == "failed"
    runs = session.query(SyncRun).all()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert "db boom" in (runs[0].error or "")
