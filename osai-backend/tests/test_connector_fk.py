"""A Composio-only connector (gmail, linear, …) has no seeded `connectors` row,
but connector_accounts / sync_runs FK to connectors.key. Writing them used to
raise ForeignKeyViolation in prod — silently failing sync and disconnect. These
tests enforce FK constraints (SQLite ignores them by default) to lock the fix.
"""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from db.models import Base, ConnectorRecord, Org, SyncRun
from db.repositories import ensure_connector_account, record_sync_result

ORG_ID = "org-1"


def _fk_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _record):  # noqa: ANN001
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    # The org exists in prod; seed it so the test isolates the connector_key FK.
    session.add(Org(id=ORG_ID, name="Acme"))
    session.commit()
    return session


def test_record_sync_result_for_composio_only_connector():
    session = _fk_session()
    # "gmail" is not a seeded connector; this used to raise ForeignKeyViolation.
    run = record_sync_result(
        session,
        org_id=ORG_ID,
        connector_key="gmail",
        status="succeeded",
        documents_seen=3,
        documents_indexed=3,
    )
    assert run.status == "succeeded"
    assert session.get(ConnectorRecord, "gmail") is not None  # created on demand
    assert session.query(SyncRun).count() == 1


def test_ensure_connector_account_for_composio_only_connector():
    session = _fk_session()
    account = ensure_connector_account(session, ORG_ID, "gmail")
    session.commit()  # commit exercises the FK; used to fail here
    assert account.connector_key == "gmail"
    assert session.get(ConnectorRecord, "gmail") is not None
