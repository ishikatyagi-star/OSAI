"""Composio OAuth-based ingestion (Notion) — structural test with a mocked client."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.schemas.connector import SourceDocument
from connectors.composio_ingest import ingest_composio_toolkit
from db.models import Base, ConnectorAccount, SourceDocumentRecord, SyncRun


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


def _assert_durable_failure(session, result, message: str) -> None:
    assert result["status"] == "failed"
    assert message.lower() in result["error"].lower()
    run = session.query(SyncRun).one()
    assert run.status == "failed"
    assert run.error == result["error"]
    account = session.query(ConnectorAccount).one()
    assert account.auth_state == "error"
    assert account.last_error == result["error"]


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
    run = session.query(SyncRun).one()
    assert run.status == "failed"
    assert "not implemented" in (run.error or "").lower()


class _UnavailableComposio(_FakeComposio):
    def available(self):
        return False


class _FailingComposio(_FakeComposio):
    async def execute(self, slug, arguments, user_id):
        raise RuntimeError("provider unavailable")


async def test_unconfigured_composio_records_failed_sync_run():
    session = _session()
    result = await ingest_composio_toolkit(
        "demo-org",
        "notion",
        session,
        client=_UnavailableComposio(),
        qdrant_store=_FakeQdrant(),
    )
    _assert_durable_failure(session, result, "not configured")


async def test_provider_fetch_failure_records_failed_sync_run():
    session = _session()
    result = await ingest_composio_toolkit(
        "demo-org",
        "notion",
        session,
        client=_FailingComposio(),
        qdrant_store=_FakeQdrant(),
    )
    _assert_durable_failure(session, result, "provider unavailable")


async def test_account_reconciliation_failure_rolls_back_and_records_failure(monkeypatch):
    from connectors import composio_ingest as ingest_module

    session = _session()

    async def fail_after_partial_write(*args, **kwargs):
        session.add(
            SourceDocumentRecord(
                id="partial-doc",
                org_id="demo-org",
                source_type="notion",
                external_id="partial",
                title="Partial",
                text="must roll back",
            )
        )
        session.flush()
        raise RuntimeError("identity reconciliation failed")

    monkeypatch.setattr(ingest_module, "_handle_account_change", fail_after_partial_write)
    result = await ingest_module.ingest_composio_toolkit(
        "demo-org",
        "notion",
        session,
        client=_FakeComposio(),
        qdrant_store=_FakeQdrant(),
    )

    _assert_durable_failure(session, result, "identity reconciliation failed")
    assert session.get(SourceDocumentRecord, "partial-doc") is None


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


async def test_provider_download_url_requires_allowlist_and_public_https(monkeypatch):
    import connectors.composio_ingest as ing

    monkeypatch.setattr(ing.settings, "composio_download_hosts", "")
    assert not await ing._download_url_allowed("https://files.example.test/object")

    monkeypatch.setattr(ing.settings, "composio_download_hosts", "files.example.test")

    def _private_dns(*_args, **_kwargs):
        return [(ing.socket.AF_INET, ing.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]

    monkeypatch.setattr(ing.socket, "getaddrinfo", _private_dns)
    assert not await ing._download_url_allowed("https://files.example.test/object")
    assert not await ing._download_url_allowed("http://files.example.test/object")
    assert not await ing._download_url_allowed("https://user@files.example.test/object")

    def _public_dns(*_args, **_kwargs):
        return [
            (ing.socket.AF_INET, ing.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ]

    monkeypatch.setattr(ing.socket, "getaddrinfo", _public_dns)
    assert await ing._download_url_allowed("https://files.example.test/object")


async def test_embedding_provider_batches_never_exceed_cap(monkeypatch):
    import connectors.composio_ingest as ing

    async def _large_document(_client, org_id, _limit):
        return [
            SourceDocument(
                source_id="notion:large",
                source_type="notion",
                org_id=org_id,
                external_id="large",
                title="Large",
                text="x" * (4_000 * (ing._EMBED_BATCH_CHUNKS + 2)),
                permissions=["source:all"],
            )
        ]

    class _BatchQdrant:
        def __init__(self):
            self.batch_sizes: list[int] = []

        async def upsert_chunks(self, chunks):
            self.batch_sizes.append(len(chunks))
            return len(chunks)

    monkeypatch.setitem(ing._FETCHERS, "notion", _large_document)
    session = _session()
    qdrant = _BatchQdrant()

    result = await ingest_composio_toolkit(
        "demo-org", "notion", session, client=_FakeComposio(), qdrant_store=qdrant
    )

    assert result["status"] == "succeeded"
    assert result["documents_embedded"] == 1
    assert len(qdrant.batch_sizes) == 2
    assert max(qdrant.batch_sizes) <= ing._EMBED_BATCH_CHUNKS


async def test_vector_failure_is_partial_not_success():
    class _FailingQdrant:
        async def upsert_chunks(self, _chunks):
            raise RuntimeError("private provider detail")

    session = _session()
    result = await ingest_composio_toolkit(
        "demo-org",
        "notion",
        session,
        client=_FakeComposio(),
        qdrant_store=_FailingQdrant(),
    )

    assert result["status"] == "partial"
    assert result["documents_indexed"] == 1
    assert result["documents_embedded"] == 0
    assert result["vector_error"] == "Vector indexing failed; retry the sync."
    assert "private provider detail" not in result["vector_error"]
    run = session.query(SyncRun).one()
    assert run.status == "partial"
    assert run.error == result["vector_error"]
