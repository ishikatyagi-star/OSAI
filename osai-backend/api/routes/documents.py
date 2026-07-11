"""Direct file upload into the org knowledge base.

Uploaded files become SourceDocuments (source_type="upload") and flow through
the exact same pipeline as connector ingestion — tier rules, Postgres chunks,
embeddings, Qdrant — so retrieval, governance, and the graph treat them like
any synced document.
"""

from __future__ import annotations

import io
import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from api.schemas.connector import SourceDocument
from db.models import Department
from db.repositories import chunks_for_documents, try_db, upsert_source_documents
from db.session import get_db, get_optional_claims, get_org_id
from memory.qdrant_store import get_default_qdrant_store

logger = logging.getLogger("osai.documents")

router = APIRouter(prefix="/documents", tags=["documents"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]

_MAX_FILE_BYTES = 15 * 1024 * 1024  # 15 MB per file
_ALLOWED_TIERS = {"normal", "amber", "red"}


def _extract_text(filename: str, data: bytes) -> str:
    """Text from an uploaded file. Raises HTTPException(415) for unsupported types."""
    name = filename.lower()
    if name.endswith((".txt", ".md", ".markdown", ".csv", ".log")):
        return data.decode("utf-8", errors="replace")
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 — malformed PDFs are a client error
            raise HTTPException(status_code=422, detail=f"Could not parse PDF: {exc}") from exc
    if name.endswith(".docx"):
        try:
            from docx import Document

            doc = Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail=f"Could not parse DOCX: {exc}") from exc
    raise HTTPException(
        status_code=415,
        detail="Unsupported file type. Supported: .txt, .md, .csv, .log, .pdf, .docx",
    )


@router.post("/upload")
async def upload_documents(
    db: DbSession,
    org_id: OrgId,
    claims: OptionalClaims,
    files: Annotated[list[UploadFile], File(...)],
    data_tier: Annotated[str, Form()] = "normal",
    permissions: Annotated[str, Form()] = "",
    department_id: Annotated[str, Form()] = "",
) -> dict:
    """Ingest uploaded files into the knowledge base.

    `data_tier` classifies the upload (normal/amber/red) and is honoured by the
    same egress policy as connector documents. `permissions` is an optional
    comma-separated list of grants; empty means org-visible ("source:all")."""
    if data_tier not in _ALLOWED_TIERS:
        raise HTTPException(
            status_code=422, detail=f"data_tier must be one of {sorted(_ALLOWED_TIERS)}"
        )
    grants = [p.strip() for p in permissions.split(",") if p.strip()] or ["source:all"]
    author = claims.get("email") or claims.get("sub") if claims else None
    # Optional department attribution — must be one of this org's departments.
    dept = department_id.strip() or None
    if dept:
        row = db.get(Department, dept)
        if row is None or row.org_id != org_id:
            raise HTTPException(status_code=422, detail="Unknown department for this workspace.")

    documents: list[SourceDocument] = []
    skipped: list[dict] = []
    for file in files:
        data = await file.read()
        if len(data) > _MAX_FILE_BYTES:
            skipped.append({"filename": file.filename, "reason": "File exceeds 15 MB limit"})
            continue
        try:
            text = _extract_text(file.filename or "unnamed", data)
        except HTTPException as exc:
            skipped.append({"filename": file.filename, "reason": exc.detail})
            continue
        if not text.strip():
            skipped.append({"filename": file.filename, "reason": "No extractable text"})
            continue
        # Tenant-safe ID: random per upload, so re-uploading the same filename
        # (here or in another org) never collides or overwrites across tenants.
        doc_id = f"upload-{uuid4()}"
        documents.append(
            SourceDocument(
                source_id=doc_id,
                source_type="upload",
                org_id=org_id,
                external_id=doc_id,
                title=file.filename or "Untitled upload",
                author=author,
                text=text,
                metadata={"origin": "direct_upload", "content_length": len(text)},
                permissions=grants,
                data_tier=data_tier,  # type: ignore[arg-type]
                department_id=dept,
            )
        )

    if not documents and skipped:
        raise HTTPException(status_code=422, detail={"skipped": skipped})

    indexed = try_db("upload_documents", 0, lambda: upsert_source_documents(db, documents))

    vectors_indexed = 0
    vector_error = None
    try:
        vectors_indexed = await get_default_qdrant_store().upsert_chunks(
            chunks_for_documents(documents)
        )
    except Exception as exc:  # noqa: BLE001 — vector indexing must not lose the upload
        vector_error = str(exc)
        logger.warning("Qdrant indexing failed for upload (org=%s): %s", org_id, exc)

    return {
        "documents_indexed": indexed,
        "vectors_indexed": vectors_indexed,
        "vector_error": vector_error,
        "skipped": skipped,
        "documents": [
            {"id": d.source_id, "title": d.title, "data_tier": d.data_tier}
            for d in documents
        ],
    }
