"""Fail-closed regressions for user-facing data and indexing routes."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from api.main import app
from api.routes import integrations
from db.session import get_db

# Regression: QA-DATA-TRUTH — outages were exposed as success or leaked provider details.
# Found by /qa on 2026-07-22
# Report: docs/qa-report-2026-07-22.md

client = TestClient(app)
_PRIVATE_FAILURE = "postgresql://admin:private-password@internal-db/production"
_QDRANT_FAILURE = "https://vector-secret@qdrant.internal:6333"


def _db_failure() -> OperationalError:
    return OperationalError("SELECT private_data", {}, RuntimeError(_PRIVATE_FAILURE))


def test_upload_persistence_failure_rolls_back_before_vector_indexing():
    db = MagicMock(spec=Session)
    store = MagicMock()
    store.upsert_chunks = AsyncMock()

    def broken_db():
        yield db

    app.dependency_overrides[get_db] = broken_db
    try:
        with (
            patch("api.routes.documents.upsert_source_documents", side_effect=_db_failure()),
            patch("api.routes.documents.get_default_qdrant_store", return_value=store) as get_store,
        ):
            response = client.post(
                "/documents/upload",
                files={"files": ("plan.txt", b"private roadmap", "text/plain")},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json() == {"detail": "Document upload is temporarily unavailable."}
    assert _PRIVATE_FAILURE not in response.text
    db.rollback.assert_called_once_with()
    get_store.assert_not_called()
    store.upsert_chunks.assert_not_awaited()


def test_upload_qdrant_failure_returns_stable_public_code(caplog):
    store = MagicMock()
    store.upsert_chunks = AsyncMock(side_effect=RuntimeError(_QDRANT_FAILURE))

    with (
        caplog.at_level(logging.WARNING, logger="osai.documents"),
        patch("api.routes.documents.get_default_qdrant_store", return_value=store),
    ):
        response = client.post(
            "/documents/upload",
            files={"files": ("notes.txt", b"meeting notes", "text/plain")},
        )

    assert response.status_code == 200
    assert response.json()["vector_error"] == "knowledge_index_update_failed"
    assert _QDRANT_FAILURE not in response.text
    assert _QDRANT_FAILURE in caplog.text


def test_access_qdrant_failure_returns_stable_public_code(caplog):
    with patch("api.routes.documents.get_default_qdrant_store") as store_factory:
        store_factory.return_value.upsert_chunks = AsyncMock(return_value=1)
        uploaded = client.post(
            "/documents/upload",
            files={"files": ("access.txt", b"sharing notes", "text/plain")},
        )
    doc_id = uploaded.json()["documents"][0]["id"]

    store = MagicMock()
    store.set_document_payload = AsyncMock(side_effect=RuntimeError(_QDRANT_FAILURE))
    with (
        caplog.at_level(logging.WARNING, logger="osai.documents"),
        patch("api.routes.documents.get_default_qdrant_store", return_value=store),
    ):
        response = client.patch(
            f"/documents/{doc_id}/access",
            json={"visibility": "company"},
        )

    assert response.status_code == 200
    assert response.json()["qdrant_error"] == "access_index_update_failed"
    assert _QDRANT_FAILURE not in response.text
    assert _QDRANT_FAILURE in caplog.text


def test_integrations_database_outage_is_not_an_empty_success(monkeypatch):
    def fail(*_args, **_kwargs):
        raise _db_failure()

    monkeypatch.setattr(integrations, "list_db_integrations", fail)
    response = client.get("/integrations")

    assert response.status_code == 503
    assert response.json() == {"detail": "Integrations are temporarily unavailable."}
    assert _PRIVATE_FAILURE not in response.text


def test_decisions_database_outage_is_not_an_empty_success():
    class BrokenSession:
        def query(self, *_args, **_kwargs):
            raise _db_failure()

    def broken_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = broken_db
    try:
        response = client.get("/decisions")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json() == {"detail": "Decisions are temporarily unavailable."}
    assert _PRIVATE_FAILURE not in response.text
