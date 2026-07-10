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
    assert {item["toolkit"] for item in result["synced"]} == {"notion", "salesforce"}
    account = session.query(ConnectorAccount).filter_by(connector_key="salesforce").one()
    assert account.auth_state == "connected"


class _FakeGmailComposio(_FakeComposio):
    async def execute(self, slug, arguments, user_id):
        if slug == "GMAIL_FETCH_EMAILS":
            return {
                "data": {
                    "response_data": {
                        "messages": [
                            {
                                "id": "message-1",
                                "snippet": "Project launch update",
                                "payload": {
                                    "headers": [
                                        {"name": "Subject", "value": "Launch update"},
                                        {"name": "From", "value": "lead@example.com"},
                                    ]
                                },
                            }
                        ]
                    }
                }
            }
        return await super().execute(slug, arguments, user_id)


async def test_gmail_ingestion_indexes_message_metadata():
    session = _session()
    result = await ingest_composio_toolkit(
        "demo-org", "gmail", session, client=_FakeGmailComposio(), qdrant_store=_FakeQdrant()
    )
    assert result["status"] == "succeeded"
    doc = session.query(SourceDocumentRecord).one()
    assert doc.id == "demo-org:gmail:message-1"
    assert doc.title == "Launch update"
    assert doc.author == "lead@example.com"


class _FakeGitHubComposio(_FakeComposio):
    async def execute(self, slug, arguments, user_id):
        if slug == "GITHUB_LIST_REPOSITORIES":
            return {
                "data": {
                    "response_data": {
                        "repositories": [
                            {
                                "id": 42,
                                "full_name": "acme/platform",
                                "description": "Core product services",
                                "html_url": "https://github.com/acme/platform",
                                "language": "Python",
                            }
                        ]
                    }
                }
            }
        return await super().execute(slug, arguments, user_id)


async def test_github_ingestion_indexes_repository_metadata():
    session = _session()
    result = await ingest_composio_toolkit(
        "demo-org", "github", session, client=_FakeGitHubComposio(), qdrant_store=_FakeQdrant()
    )
    assert result["status"] == "succeeded"
    doc = session.query(SourceDocumentRecord).one()
    assert doc.id == "demo-org:github:42"
    assert doc.title == "acme/platform"
    assert doc.url == "https://github.com/acme/platform"
