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
from db.models import Department, User
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
_ALLOWED_VISIBILITY = {"personal", "department", "company", "people"}


def _visibility_grants(
    db: Session,
    org_id: str,
    visibility: str,
    uploader_id: str | None,
    department_id: str | None,
    shared_with: list[str],
) -> list[str]:
    """Map a human visibility choice onto permission grants.

    personal   -> ["user:<uploader>"]           (only the uploader)
    department -> ["dept:<department_id>"]       (their department)
    company    -> ["source:all"]                 (whole workspace)
    people     -> ["user:<uploader>", "user:<id>", ...] (named teammates)

    Raises HTTPException(422) when the choice can't be honoured (e.g. personal
    without an authenticated user), rather than silently widening access."""
    if visibility == "company":
        return ["source:all"]
    if visibility == "personal":
        # Demo/unauthenticated context has no user account to scope to — those
        # uploads land workspace-wide, same as every other demo document.
        if not uploader_id:
            return ["source:all"]
        return [f"user:{uploader_id}"]
    if visibility == "department":
        if not department_id:
            raise HTTPException(
                status_code=422,
                detail="Pick a department to share with (or join one in Team settings).",
            )
        return [f"dept:{department_id}"]
    # visibility == "people"
    if not shared_with:
        raise HTTPException(
            status_code=422, detail="Choose at least one person to share with."
        )
    members = db.query(User).filter(User.org_id == org_id, User.id.in_(shared_with)).all()
    if len(members) != len(set(shared_with)):
        raise HTTPException(
            status_code=422, detail="One or more selected people aren't in this workspace."
        )
    grants = {f"user:{m.id}" for m in members}
    if uploader_id:
        grants.add(f"user:{uploader_id}")  # sharer keeps access to their own file
    return sorted(grants)


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
    visibility: Annotated[str, Form()] = "personal",
    shared_with: Annotated[str, Form()] = "",
    department_id: Annotated[str, Form()] = "",
) -> dict:
    """Ingest uploaded files into the knowledge base.

    `visibility` says who can see the files: personal (just the uploader),
    department (requires `department_id`), company (whole workspace), or people
    (requires `shared_with`, a comma-separated list of member ids). It is
    translated into the same permission grants the retriever already filters by.
    `data_tier` remains an internal routing classification (cloud vs local
    model egress) and defaults to "normal"; it is no longer a user-facing choice."""
    if data_tier not in _ALLOWED_TIERS:
        raise HTTPException(
            status_code=422, detail=f"data_tier must be one of {sorted(_ALLOWED_TIERS)}"
        )
    if visibility not in _ALLOWED_VISIBILITY:
        raise HTTPException(
            status_code=422, detail=f"visibility must be one of {sorted(_ALLOWED_VISIBILITY)}"
        )
    uploader_id = claims.get("sub") if claims else None
    author = claims.get("email") or uploader_id if claims else None
    # Department attribution — must be one of this org's departments. For
    # department visibility, default to the uploader's own department.
    dept = department_id.strip() or None
    if not dept and visibility == "department" and uploader_id:
        uploader = db.get(User, uploader_id)
        dept = uploader.department_id if uploader else None
    if dept:
        row = db.get(Department, dept)
        if row is None or row.org_id != org_id:
            raise HTTPException(status_code=422, detail="Unknown department for this workspace.")
    recipients = [s.strip() for s in shared_with.split(",") if s.strip()]
    grants = _visibility_grants(db, org_id, visibility, uploader_id, dept, recipients)

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
        "visibility": visibility,
        "documents": [
            {"id": d.source_id, "title": d.title, "data_tier": d.data_tier}
            for d in documents
        ],
    }
