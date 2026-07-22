"""Direct file upload into the org knowledge base.

Uploaded files become SourceDocuments (source_type="upload") and flow through
the exact same pipeline as connector ingestion — tier rules, Postgres chunks,
embeddings, Qdrant — so retrieval, governance, and the graph treat them like
any synced document.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import uuid4

import anyio
import anyio.to_process
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from api.document_extraction import MAX_FILE_BYTES, extract_document_text
from api.ratelimit import INGEST_START_BUDGET, rate_limit
from api.schemas.connector import SourceDocument
from db.models import Chunk, Department, Notification, SourceDocumentRecord, User
from db.repositories import (
    AmbiguousUserEmailError,
    chunks_for_documents,
    find_user_by_email,
    upsert_source_documents,
)
from db.session import get_db, get_optional_claims, get_org_id, require_writable_org
from memory.qdrant_store import get_default_qdrant_store

logger = logging.getLogger("osai.documents")

_MAX_FILES_PER_REQUEST = 10
_MAX_BATCH_BYTES = 30 * 1024 * 1024
_MAX_MULTIPART_BYTES = _MAX_BATCH_BYTES + 1024 * 1024
_PARSER_TIMEOUT_SECONDS = 10
_DOCUMENT_STORE_UNAVAILABLE = "Document upload is temporarily unavailable."
_VECTOR_INDEX_ERROR = "knowledge_index_update_failed"
_ACCESS_INDEX_ERROR = "access_index_update_failed"
# Admission is acquired before multipart consumption and held through extraction.
# It bounds both spooled requests and the raw bytes serialized to parser workers.
_UPLOAD_ADMISSION_LIMITER = anyio.CapacityLimiter(2)
_PARSER_PROCESS_LIMITER = anyio.CapacityLimiter(2)


router = APIRouter(prefix="/documents", tags=["documents"])
DbSession = Annotated[Session, Depends(get_db)]
OrgId = Annotated[str, Depends(get_org_id)]
# Uploading indexes data + spends embeddings; changing access rewrites grants.
# Neither is reachable from the anonymous demo workspace (SEC-003).
WriteOrgId = Annotated[str, Depends(require_writable_org)]
OptionalClaims = Annotated[dict | None, Depends(get_optional_claims)]

_ALLOWED_TIERS = {"normal", "amber", "red"}
_ALLOWED_VISIBILITY = {"personal", "department", "company", "people"}


class _StrictMultiPartParser(MultiPartParser):
    """Require the terminal boundary and close every spool on rejected input."""

    saw_end = False

    def on_end(self) -> None:
        self.saw_end = True
        super().on_end()

    def close_files(self) -> None:
        # Starlette closes this list for MultiPartException, but not for
        # python-multipart's MultipartParseError or a missing terminal boundary.
        for file in self._files_to_close_on_error:
            file.close()


def _require_upload_content_type(request: Request) -> None:
    """Reject non-multipart uploads without consuming their request bodies."""
    media_type, _ = parse_options_header(request.headers.get("content-type"))
    if media_type.lower() != b"multipart/form-data":
        raise HTTPException(
            status_code=415,
            detail="Content-Type must be multipart/form-data",
        )


async def _bounded_upload_form(
    request: Request,
    _org_id: Annotated[str, Depends(require_writable_org)],
) -> AsyncIterator[FormData]:
    """Authenticate, admit, and only then materialize a bounded multipart form."""

    async def limited_stream() -> AsyncIterator[bytes]:
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > _MAX_MULTIPART_BYTES:
                raise MultiPartException("Upload exceeds 31 MB request limit")
            yield chunk

    async with _UPLOAD_ADMISSION_LIMITER:
        parser = _StrictMultiPartParser(
            request.headers,
            limited_stream(),
            max_files=_MAX_FILES_PER_REQUEST,
            max_fields=4,
            max_part_size=64 * 1024,
        )
        try:
            form = await parser.parse()
        except MultiPartException as exc:
            parser.close_files()
            status_code = (
                413
                if exc.message.startswith(
                    ("Too many files", "Too many fields", "Part exceeded", "Upload exceeds")
                )
                else 400
            )
            raise HTTPException(status_code=status_code, detail=exc.message) from exc
        except MultipartParseError as exc:
            parser.close_files()
            # python-multipart raises this directly for invalid boundaries/headers;
            # never let malformed wire input escape as an internal server error.
            raise HTTPException(status_code=400, detail="Malformed multipart body") from exc
        except BaseException:
            parser.close_files()
            raise

        if not parser.saw_end:
            parser.close_files()
            raise HTTPException(status_code=400, detail="Malformed multipart body")

        try:
            yield form
        finally:
            await form.close()


def _string_form_value(form: FormData, name: str, default: str) -> str:
    value = form.get(name, default)
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{name} must be a text field")
    return value


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
        # Drive-style: named people can be added on top of department access.
        return sorted({f"dept:{department_id}", *_user_grants(db, org_id, shared_with)})
    # visibility == "people"
    if not shared_with:
        raise HTTPException(status_code=422, detail="Choose at least one person to share with.")
    grants = set(_user_grants(db, org_id, shared_with))
    if uploader_id:
        grants.add(f"user:{uploader_id}")  # sharer keeps access to their own file
    return sorted(grants)


def _user_grants(db: Session, org_id: str, user_ids: list[str]) -> list[str]:
    """Validated "user:<id>" grants for workspace members."""
    if not user_ids:
        return []
    members = db.query(User).filter(User.org_id == org_id, User.id.in_(user_ids)).all()
    if len(members) != len(set(user_ids)):
        raise HTTPException(
            status_code=422, detail="One or more selected people aren't in this workspace."
        )
    return [f"user:{m.id}" for m in members]


async def _extract_text(filename: str, data: bytes) -> str:
    """Extract in a killable worker process so parser failures cannot block the API loop."""
    try:
        with anyio.fail_after(_PARSER_TIMEOUT_SECONDS):
            status, result = await anyio.to_process.run_sync(
                extract_document_text,
                filename,
                data,
                cancellable=True,
                limiter=_PARSER_PROCESS_LIMITER,
            )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=413,
            detail=f"Document parsing exceeded {_PARSER_TIMEOUT_SECONDS} second limit",
        ) from exc
    except anyio.BrokenWorkerProcess as exc:
        raise HTTPException(
            status_code=413, detail="Document parser exceeded its resource limit"
        ) from exc

    if status == "ok":
        return result
    status_code = 415 if status == "unsupported" else 413 if status == "limit" else 422
    raise HTTPException(status_code=status_code, detail=result)


@router.post(
    "/upload",
    dependencies=[
        Depends(_require_upload_content_type),
        Depends(rate_limit(*INGEST_START_BUDGET)),
    ],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["files"],
                        "properties": {
                            "files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                            },
                            "data_tier": {"type": "string", "default": "normal"},
                            "visibility": {"type": "string", "default": "personal"},
                            "shared_with": {"type": "string", "default": ""},
                            "department_id": {"type": "string", "default": ""},
                        },
                    }
                }
            },
        }
    },
)
async def upload_documents(
    db: DbSession,
    org_id: WriteOrgId,
    claims: OptionalClaims,
    form: Annotated[FormData, Depends(_bounded_upload_form)],
) -> dict:
    """Ingest uploaded files into the knowledge base.

    `visibility` says who can see the files: personal (just the uploader),
    department (requires `department_id`), company (whole workspace), or people
    (requires `shared_with`, a comma-separated list of member ids). It is
    translated into the same permission grants the retriever already filters by.
    `data_tier` remains an internal routing classification (cloud vs local
    model egress) and defaults to "normal"; it is no longer a user-facing choice."""
    file_values = form.getlist("files")
    if not file_values or any(not isinstance(value, UploadFile) for value in file_values):
        raise HTTPException(status_code=422, detail="At least one file is required")
    files = [value for value in file_values if isinstance(value, UploadFile)]
    data_tier = _string_form_value(form, "data_tier", "normal")
    visibility = _string_form_value(form, "visibility", "personal")
    shared_with = _string_form_value(form, "shared_with", "")
    department_id = _string_form_value(form, "department_id", "")

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
    if len(files) > _MAX_FILES_PER_REQUEST:
        raise HTTPException(status_code=413, detail="Upload accepts at most 10 files per request")

    known_batch_bytes = sum(
        file.size for file in files if file.size is not None and file.size <= MAX_FILE_BYTES
    )
    if known_batch_bytes > _MAX_BATCH_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds 30 MB batch limit")

    batch_bytes = 0
    for file in files:
        filename = file.filename or "unnamed"
        if file.size is not None and file.size > MAX_FILE_BYTES:
            skipped.append({"filename": file.filename, "reason": "File exceeds 15 MB limit"})
            continue
        data = await file.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            skipped.append({"filename": file.filename, "reason": "File exceeds 15 MB limit"})
            del data
            continue
        batch_bytes += len(data)
        if batch_bytes > _MAX_BATCH_BYTES:
            raise HTTPException(status_code=413, detail="Upload exceeds 30 MB batch limit")
        try:
            text = await _extract_text(filename, data)
        except HTTPException as exc:
            skipped.append({"filename": filename, "reason": exc.detail})
            continue
        finally:
            # Do not retain a second full-batch copy while parser jobs queue.
            del data
        if not text.strip():
            skipped.append({"filename": filename, "reason": "No extractable text"})
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
                title=filename if filename != "unnamed" else "Untitled upload",
                author=author,
                text=text,
                metadata={
                    "origin": "direct_upload",
                    "content_length": len(text),
                    "uploader_id": uploader_id,
                },
                permissions=grants,
                data_tier=data_tier,  # type: ignore[arg-type]
                department_id=dept,
            )
        )

    if not documents and skipped:
        raise HTTPException(status_code=422, detail={"skipped": skipped})

    def _persist() -> int:
        n = upsert_source_documents(db, documents)
        # upsert_source_documents flushes but doesn't commit (connector syncs
        # commit at the sync-run level); commit here or the upload evaporates
        # when this request's session closes.
        db.commit()
        return n

    try:
        indexed = _persist()
    except SQLAlchemyError as exc:
        logger.exception("Document persistence failed for upload (org=%s)", org_id)
        try:
            db.rollback()
        except SQLAlchemyError:
            logger.exception("Document upload rollback failed (org=%s)", org_id)
        raise HTTPException(status_code=503, detail=_DOCUMENT_STORE_UNAVAILABLE) from exc

    vectors_indexed = 0
    vector_error = None
    try:
        vectors_indexed = await get_default_qdrant_store().upsert_chunks(
            chunks_for_documents(documents)
        )
    except Exception as exc:  # noqa: BLE001 — vector indexing must not lose the upload
        vector_error = _VECTOR_INDEX_ERROR
        logger.warning("Qdrant indexing failed for upload (org=%s): %s", org_id, exc)

    return {
        "documents_indexed": indexed,
        "vectors_indexed": vectors_indexed,
        "vector_error": vector_error,
        "skipped": skipped,
        "visibility": visibility,
        "documents": [
            {"id": d.source_id, "title": d.title, "data_tier": d.data_tier} for d in documents
        ],
    }


def _derive_visibility(record: SourceDocumentRecord) -> dict:
    """Reverse-map stored grants back to the human visibility model."""
    perms = record.permissions or []
    user_ids = [p.removeprefix("user:") for p in perms if p.startswith("user:")]
    if perms and all(p.startswith("user:") for p in perms):
        visibility = "personal" if len(user_ids) == 1 else "people"
    elif any(p.startswith("dept:") for p in perms):
        visibility = "department"
    else:
        visibility = "company"
    return {
        "visibility": visibility,
        "shared_with": user_ids,
        "department_id": record.department_id,
    }


def _upload_owner_id(record: SourceDocumentRecord, db: Session) -> str | None:
    """Resolve a direct upload's owner without trusting connector author fields."""
    if record.source_type != "upload":
        return None
    metadata = record.metadata_json if isinstance(record.metadata_json, dict) else {}
    stored_id = metadata.get("uploader_id")
    if isinstance(stored_id, str) and stored_id:
        user = db.get(User, stored_id)
        if user is not None and user.org_id == record.org_id:
            return user.id
    if record.author:
        # Backward compatibility for uploads created before uploader_id was
        # persisted. Scope the lookup to this workspace and upload source.
        legacy_owner = db.get(User, record.author)
        if legacy_owner is not None and legacy_owner.org_id == record.org_id:
            return legacy_owner.id
        try:
            legacy_owner = find_user_by_email(db, record.author, org_id=record.org_id)
        except AmbiguousUserEmailError:
            logger.error("refused ambiguous legacy upload-owner mapping (org=%s)", record.org_id)
            return None
        if legacy_owner is not None:
            return legacy_owner.id
    return None


def _can_manage(record: SourceDocumentRecord, claims: dict | None, db: Session) -> bool:
    """Only the direct upload's owner or a current workspace admin may manage it."""
    if claims is None:
        return True  # demo/unauthenticated context manages demo data freely
    user_id = claims.get("sub")
    user = db.get(User, user_id) if user_id else None
    if user is None or user.org_id != record.org_id:
        return False
    return user.id == _upload_owner_id(record, db) or user.role == "admin"


def _get_upload_record(db: Session, org_id: str, doc_id: str) -> SourceDocumentRecord:
    record = db.get(SourceDocumentRecord, doc_id)
    if record is None or record.org_id != org_id or record.source_type != "upload":
        raise HTTPException(status_code=404, detail="Document not found.")
    return record


@router.get("/{doc_id}/access")
async def get_document_access(
    db: DbSession, org_id: OrgId, claims: OptionalClaims, doc_id: str
) -> dict:
    record = _get_upload_record(db, org_id, doc_id)
    if claims is None or not _can_manage(record, claims, db):
        raise HTTPException(
            status_code=403,
            detail="Only the uploader or an admin can view full sharing access.",
        )
    access = _derive_visibility(record)
    members = (
        db.query(User).filter(User.org_id == org_id, User.id.in_(access["shared_with"])).all()
        if access["shared_with"]
        else []
    )
    access["people"] = [
        {"id": m.id, "name": m.display_name or m.email, "email": m.email} for m in members
    ]
    access["title"] = record.title
    return access


class AccessUpdate(BaseModel):
    visibility: str
    shared_with: list[str] = Field(default_factory=list)
    department_id: str | None = None


@router.patch("/{doc_id}/access")
async def update_document_access(
    db: DbSession,
    org_id: WriteOrgId,
    claims: OptionalClaims,
    doc_id: str,
    body: AccessUpdate,
) -> dict:
    """Change who can see an already-uploaded document (Drive-style manage
    access). Rewrites the grants in Postgres and on the Qdrant chunk payloads,
    and notifies newly-added people."""
    if body.visibility not in _ALLOWED_VISIBILITY:
        raise HTTPException(
            status_code=422, detail=f"visibility must be one of {sorted(_ALLOWED_VISIBILITY)}"
        )
    record = _get_upload_record(db, org_id, doc_id)
    if not _can_manage(record, claims, db):
        raise HTTPException(
            status_code=403, detail="Only the uploader or an admin can change access."
        )

    actor_id = claims.get("sub") if claims else None
    uploader_id = _upload_owner_id(record, db)
    if body.visibility in {"personal", "people"} and not uploader_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "The original uploader could not be identified; choose department "
                "or company access."
            ),
        )
    dept = (body.department_id or "").strip() or None
    if not dept and body.visibility == "department" and uploader_id:
        uploader = db.get(User, uploader_id)
        dept = uploader.department_id if uploader else None
    if dept:
        row = db.get(Department, dept)
        if row is None or row.org_id != org_id:
            raise HTTPException(status_code=422, detail="Unknown department for this workspace.")

    previous = set(record.permissions or [])
    grants = _visibility_grants(db, org_id, body.visibility, uploader_id, dept, body.shared_with)

    record.permissions = grants
    record.department_id = dept if body.visibility == "department" else record.department_id
    db.query(Chunk).filter(Chunk.source_document_id == doc_id).update(
        {"permissions": grants}, synchronize_session=False
    )

    # Notify people who just gained access (not the actor themselves).
    actor = db.get(User, actor_id) if actor_id else None
    new_user_ids = {
        g.removeprefix("user:") for g in set(grants) - previous if g.startswith("user:")
    } - {actor_id}
    removed_user_ids = {
        g.removeprefix("user:") for g in previous - set(grants) if g.startswith("user:")
    }
    if removed_user_ids:
        db.query(Notification).filter(
            Notification.org_id == org_id,
            Notification.user_id.in_(removed_user_ids),
            Notification.type == "document.shared",
            Notification.payload["document_id"].as_string() == doc_id,
        ).delete(synchronize_session=False)
    for target in new_user_ids:
        db.add(
            Notification(
                org_id=org_id,
                user_id=target,
                type="document.shared",
                payload={
                    "document_id": doc_id,
                    "title": record.title,
                    "shared_by": (actor.display_name or actor.email) if actor else "A teammate",
                },
            )
        )
    db.commit()

    qdrant_error = None
    try:
        await get_default_qdrant_store().set_document_payload(
            org_id, doc_id, {"permissions": grants}
        )
    except Exception as exc:  # noqa: BLE001 — Postgres is source of truth; surface lag honestly
        qdrant_error = _ACCESS_INDEX_ERROR
        logger.warning("Qdrant payload update failed (org=%s doc=%s): %s", org_id, doc_id, exc)

    return {**_derive_visibility(record), "qdrant_error": qdrant_error}
