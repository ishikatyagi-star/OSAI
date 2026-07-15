"""Reconnecting a Composio connector with a different external account must
purge the previous account's indexed data so counts and Ask reflect only the
currently-connected account (see the Google Drive reconnect QA findings)."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from connectors.composio_ingest import ingest_composio_toolkit, purge_connector_data
from db.models import Base, ConnectorAccount, SourceDocumentRecord


class _FakeDrive:
    """Fake Composio client for a Google Drive connection whose account and files
    can be swapped between syncs to simulate a reconnect."""

    def __init__(self, account_id: str, email: str, files: list[tuple[str, str, str]]):
        self.account_id = account_id
        self.email = email
        self.files = files  # (drive_id, name, text)

    def available(self):
        return True

    async def connection_identity(self, toolkit, user_id):
        return {"id": self.account_id, "email": self.email}

    async def list_connections(self, user_id):
        return [
            {
                "id": self.account_id,
                "toolkit": "googledrive",
                "status": "ACTIVE",
                "email": self.email,
            }
        ]

    async def execute(self, slug, arguments, user_id):
        if slug == "GOOGLEDRIVE_LIST_FILES":
            return {
                "data": {
                    "files": [
                        {"id": fid, "name": name, "webViewLink": f"https://drive/{fid}"}
                        for fid, name, _ in self.files
                    ]
                }
            }
        if slug == "GOOGLEDRIVE_DOWNLOAD_FILE":
            fid = arguments["file_id"]
            text = next((t for f, _, t in self.files if f == fid), "")
            return {"data": {"text": text}}
        return {"successful": False, "data": None, "error": "unknown"}


class _FakeQdrant:
    def __init__(self):
        self.deleted_source_types: list[tuple[str, str]] = []

    async def upsert_chunks(self, chunks):
        return len(chunks)

    async def delete_source_type(self, org_id, source_type):
        self.deleted_source_types.append((org_id, source_type))


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


async def test_reconnect_with_different_account_purges_previous_docs():
    session = _session()
    qdrant = _FakeQdrant()

    # Account A syncs two documents.
    account_a = _FakeDrive(
        "ca_A",
        "alice@a.com",
        [("f1", "roadmap.txt", "Q3 roadmap"), ("f2", "notes.txt", "meeting notes")],
    )
    await ingest_composio_toolkit(
        "demo-org", "googledrive", session, client=account_a, qdrant_store=qdrant
    )
    drive_docs = (
        session.query(SourceDocumentRecord)
        .filter(SourceDocumentRecord.source_type == "google_drive")
        .all()
    )
    assert {d.external_id for d in drive_docs} == {"f1", "f2"}

    # Reconnect with Account B (different id) that has one, different file.
    account_b = _FakeDrive("ca_B", "bob@b.com", [("f3", "budget.txt", "2026 budget")])
    await ingest_composio_toolkit(
        "demo-org", "googledrive", session, client=account_b, qdrant_store=qdrant
    )

    drive_docs = (
        session.query(SourceDocumentRecord)
        .filter(SourceDocumentRecord.source_type == "google_drive")
        .all()
    )
    # Account A's files are gone; only Account B's file remains.
    assert {d.external_id for d in drive_docs} == {"f3"}

    # Vectors for the connector were purged on the account change.
    assert ("demo-org", "google_drive") in qdrant.deleted_source_types

    # The stored identity now reflects Account B, and remembers the previous one.
    account = (
        session.query(ConnectorAccount)
        .filter(ConnectorAccount.connector_key == "google_drive")
        .one()
    )
    assert account.config["account_external_id"] == "ca_B"
    assert account.config["account_email"] == "bob@b.com"
    assert account.config["previous_account_email"] == "alice@a.com"
    assert account.config.get("last_reconnected_at")


async def test_disconnect_purges_synced_docs_and_clears_identity():
    """Disconnecting a connector deletes everything the connected account synced
    (Postgres + Qdrant) and clears the stored identity, so a later reconnect with
    a new account starts clean and cannot mix the two accounts' files."""
    session = _session()
    qdrant = _FakeQdrant()

    account_a = _FakeDrive(
        "ca_A",
        "alice@a.com",
        [("f1", "roadmap.txt", "Q3 roadmap"), ("f2", "notes.txt", "meeting notes")],
    )
    await ingest_composio_toolkit(
        "demo-org", "googledrive", session, client=account_a, qdrant_store=qdrant
    )
    assert session.query(SourceDocumentRecord).count() == 2

    removed = await purge_connector_data(
        session, "demo-org", "googledrive", qdrant_store=qdrant
    )
    session.commit()

    assert removed == 2
    # Postgres docs gone…
    assert (
        session.query(SourceDocumentRecord)
        .filter(SourceDocumentRecord.source_type == "google_drive")
        .count()
        == 0
    )
    # …Qdrant vectors purged…
    assert ("demo-org", "google_drive") in qdrant.deleted_source_types
    # …and the account is marked disconnected with no lingering identity.
    account = (
        session.query(ConnectorAccount)
        .filter(ConnectorAccount.connector_key == "google_drive")
        .one()
    )
    assert account.auth_state == "disconnected"
    assert "account_external_id" not in account.config
    assert "account_email" not in account.config
    assert account.last_sync_at is None


async def test_resync_same_account_does_not_purge():
    session = _session()
    qdrant = _FakeQdrant()
    drive = _FakeDrive("ca_A", "alice@a.com", [("f1", "roadmap.txt", "Q3 roadmap")])

    await ingest_composio_toolkit(
        "demo-org", "googledrive", session, client=drive, qdrant_store=qdrant
    )
    # A second sync from the same account should not trigger a purge.
    drive.files = [("f1", "roadmap.txt", "Q3 roadmap v2"), ("f2", "new.txt", "new file")]
    await ingest_composio_toolkit(
        "demo-org", "googledrive", session, client=drive, qdrant_store=qdrant
    )

    assert qdrant.deleted_source_types == []
    drive_docs = (
        session.query(SourceDocumentRecord)
        .filter(SourceDocumentRecord.source_type == "google_drive")
        .all()
    )
    assert {d.external_id for d in drive_docs} == {"f1", "f2"}
