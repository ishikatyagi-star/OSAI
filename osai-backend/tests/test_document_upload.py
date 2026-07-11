"""Direct file upload into the knowledge base (POST /documents/upload)."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, patch

from docx import Document as DocxDocument
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _upload(files, data=None):
    with patch("api.routes.documents.get_default_qdrant_store") as mock_store:
        mock_store.return_value.upsert_chunks = AsyncMock(return_value=len(files))
        return client.post("/documents/upload", files=files, data=data or {})


def test_upload_txt_ingests_document():
    resp = _upload(
        [("files", ("notes.txt", b"Quarterly planning notes: ship the pilot.", "text/plain"))]
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["documents_indexed"] == 1
    assert body["skipped"] == []
    doc = body["documents"][0]
    assert doc["title"] == "notes.txt"
    assert doc["data_tier"] == "normal"
    assert doc["id"].startswith("upload-")


def test_upload_docx_extracts_paragraphs():
    buf = io.BytesIO()
    d = DocxDocument()
    d.add_paragraph("Decision: adopt Qdrant for vectors.")
    d.save(buf)
    docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    resp = _upload([("files", ("decision.docx", buf.getvalue(), docx_mime))])
    assert resp.status_code == 200
    assert resp.json()["documents_indexed"] == 1


def test_upload_respects_tier_and_permissions():
    resp = _upload(
        [("files", ("salary.txt", b"Compensation bands for 2026.", "text/plain"))],
        data={"data_tier": "red", "permissions": "source:hr, role:admin"},
    )
    assert resp.status_code == 200
    assert resp.json()["documents"][0]["data_tier"] == "red"


def test_upload_rejects_bad_tier():
    resp = _upload(
        [("files", ("a.txt", b"x", "text/plain"))],
        data={"data_tier": "topsecret"},
    )
    assert resp.status_code == 422


def test_unsupported_type_is_skipped_with_reason():
    resp = _upload([("files", ("binary.exe", b"\x00\x01", "application/octet-stream"))])
    assert resp.status_code == 422  # nothing ingestible
    detail = resp.json()["detail"]
    assert detail["skipped"][0]["filename"] == "binary.exe"


def test_mixed_batch_ingests_good_and_reports_skipped():
    resp = _upload(
        [
            ("files", ("ok.md", b"# Runbook\nRestart the worker.", "text/markdown")),
            ("files", ("bad.exe", b"\x00", "application/octet-stream")),
        ]
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["documents_indexed"] == 1
    assert len(body["skipped"]) == 1


def test_upload_requires_auth():
    from db.session import get_org_id

    app.dependency_overrides.pop(get_org_id, None)
    resp = TestClient(app).post(
        "/documents/upload",
        files=[("files", ("a.txt", b"hello", "text/plain"))],
    )
    assert resp.status_code == 401
