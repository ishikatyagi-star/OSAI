import logging
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import and_, desc, func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from api.schemas.connector import SourceDocument
from db.models import (
    ActionItemRecord,
    AskExchange,
    AuditEvent,
    Automation,
    AutomationTriggerRequest,
    Chunk,
    ConnectorAccount,
    ConnectorAction,
    ConnectorRecord,
    Department,
    Invite,
    Notification,
    Org,
    OrgMemory,
    SavedArtifact,
    SourceDocumentRecord,
    SyncRun,
    Thread,
    User,
    WorkflowRun,
    normalize_email,
    now_utc,
    utc_iso,
)
from db.session import SessionLocal
from memory.chunker import chunk_document

logger = logging.getLogger("osai.repositories")
UNSET: object = object()


class AmbiguousUserEmailError(RuntimeError):
    """Raised when a legacy database has multiple rows for one email identity."""


def find_user_by_email(
    session: Session,
    email: str,
    *,
    org_id: str | None = None,
) -> User | None:
    """Resolve exactly one normalized email identity, failing closed on collisions."""
    normalized = normalize_email(email)
    if not normalized:
        return None
    predicates = [func.lower(func.trim(User.email)) == normalized]
    if org_id is not None:
        predicates.append(User.org_id == org_id)
    matches = session.scalars(select(User).where(*predicates).limit(2)).all()
    if len(matches) > 1:
        raise AmbiguousUserEmailError("Multiple user records share one normalized email identity.")
    return matches[0] if matches else None


def seed_demo_data(session: Session, org_id: str = "demo-org") -> None:
    if session.get(Org, org_id) is None:
        session.add(Org(id=org_id, name="OSAI Demo Org"))
        session.flush()
    if find_user_by_email(session, "admin@osai.local") is None:
        session.add(
            User(
                org_id=org_id,
                email="admin@osai.local",
                display_name="OSAI Admin",
                permissions=["org:admin", "source:all"],
            )
        )
    for key, name, capabilities in [
        ("notion", "Notion", ["sync", "search", "execute"]),
        ("slack", "Slack", ["sync", "search", "execute"]),
        ("freshdesk", "Freshdesk", ["sync", "search", "execute"]),
        ("google_drive", "Google Drive", ["sync", "search"]),
    ]:
        if session.get(ConnectorRecord, key) is None:
            session.add(ConnectorRecord(key=key, display_name=name, capabilities=capabilities))
            session.flush()
        account = session.scalar(
            select(ConnectorAccount).where(
                ConnectorAccount.org_id == org_id,
                ConnectorAccount.connector_key == key,
            )
        )
        if account is None:
            session.add(ConnectorAccount(org_id=org_id, connector_key=key))
    session.add(AuditEvent(org_id=org_id, event_type="seed.demo_data", actor="system"))
    session.commit()


def _get_mock_docs(org_id: str) -> list[dict[str, str]]:
    return [
        {
            "id": "doc-linear-integration",
            "title": "Linear Sync Integration Guidelines",
            "text": (
                "OSAI integrates with Linear to automatically create developer issues. "
                "The mapping connects extracted assignee emails to active Linear user IDs. "
                "To enable auto-push, make sure to grant read/write scope. "
                "The default destination project is defined in the connector configuration "
                "payload. If the assignee does not match any team email, the ticket is "
                "created unassigned."
            ),
            "source_type": "notion",
            "external_id": "notion-linear-1",
        },
        {
            "id": "doc-data-tiering",
            "title": "Data Tiering and Classification Rules",
            "text": (
                "Data in OSAI is classified into three tiers: Normal, Amber, and Red. "
                "Normal tier allows all cloud API routing. Amber tier restricts certain "
                "third-party connectors and disables cloud LLMs (only runs search). "
                "Red tier strictly enforces local execution via Ollama (Llama3/Mistral) "
                "and private VPC Qdrant storage. No external requests are allowed under "
                "Red tier configurations."
            ),
            "source_type": "google_drive",
            "external_id": "drive-data-1",
        },
        {
            "id": "doc-slack-onboarding",
            "title": "OSAI Team Onboarding Guidelines",
            "text": (
                "Welcome to the OSAI team! Make sure to read the onboarding guide in Notion "
                "and hook up your Linear accounts. Our developer environment resides in "
                "Docker, communicating over the internal bridge network. Ensure your "
                "local .env is properly populated. The API is hosted on port 8000, "
                "and Qdrant runs on port 6333."
            ),
            "source_type": "slack",
            "external_id": "slack-channel-onboarding",
        },
        {
            "id": "doc-freshdesk-sla",
            "title": "Freshdesk Integration & SLA Escalation Rules",
            "text": (
                "OSAI maps incoming support tickets to active developer actions. Under normal "
                "conditions, tickets are synced every 30 minutes. If a ticket transitions to "
                "urgent, an alert is triggered in the Slack #operations channel. If the "
                "customer is on an Enterprise plan, the ticket must be resolved within 4 hours, "
                "and all action items must be automatically pushed."
            ),
            "source_type": "freshdesk",
            "external_id": "freshdesk-ticket-102",
        },
        {
            "id": "doc-vpc-configuration",
            "title": "VPC and Ollama Security Setup",
            "text": (
                "To protect company secrets, all Red-tier processing happens strictly within "
                "private VPC subnets. The Ollama service runs llama3 or mistral locally. Any "
                "external APIs or network calls are blocked. Qdrant is hosted on a private "
                "endpoint. The database uses SSL client certificates to authenticate inbound "
                "requests from the Celery worker."
            ),
            "source_type": "notion",
            "external_id": "notion-vpc-sec",
        },
    ]


async def index_seeded_chunks_to_qdrant(org_id: str = "demo-org") -> None:
    from memory.qdrant_store import get_default_qdrant_store

    qdrant = get_default_qdrant_store()
    docs = _get_mock_docs(org_id)
    chunks = []
    for d in docs:
        # Most docs are public; security material is restricted to demonstrate
        # permission-aware retrieval (data governance).
        is_security = any(kw in (d["title"] or "").lower() for kw in ("security", "vpc", "ollama"))
        chunks.append(
            {
                "chunk_id": f"chunk-{d['id']}",
                "source_document_id": d["id"],
                "org_id": org_id,
                "source_type": d["source_type"],
                "content_preview": d["text"][:100] + "...",
                "text": d["text"],
                "metadata": {"title": d["title"]},
                "permissions": ["role:security"] if is_security else ["source:all"],
                "data_tier": "amber" if is_security else "normal",
            }
        )
    await qdrant.upsert_chunks(chunks)


def seed_rich_demo_data(session: Session, org_id: str = "demo-org") -> None:
    # First seed base data
    seed_demo_data(session, org_id)

    # Seed Rich Mock Workflow Runs & Action Items
    import datetime
    from uuid import uuid4

    if session.query(WorkflowRun).count() == 0:
        runs_data = [
            {
                "id": "workflow-architecture-align",
                "org_id": org_id,
                "kind": "meeting_action_items",
                "status": "needs_review",
                "input_text": (
                    "Anish: I will write the Zoom webhook endpoint by next Tuesday.\n"
                    "Ishika: I will prepare the UI mockups for settings panel by Friday."
                ),
                "destination": "manual",
                "data_tier": "normal",
                "model_route": "gemini-2.0-flash",
                "created_at": datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=2),
                "action_items": [
                    {
                        "title": "Write the Zoom webhook endpoint",
                        "owner": "anish@osai.local",
                        "due_date": "2026-06-09",
                        "source_quote": (
                            "Anish: I will write the Zoom webhook endpoint by next Tuesday."
                        ),
                        "destination": "slack",
                        "confidence": 0.95,
                        "status": "needs_review",
                    },
                    {
                        "title": "Prepare the UI mockups for settings panel",
                        "owner": "ishika@osai.local",
                        "due_date": "2026-06-05",
                        "source_quote": (
                            "Ishika: I will prepare the UI mockups for settings panel by Friday."
                        ),
                        "destination": "notion",
                        "confidence": 0.90,
                        "status": "needs_review",
                    },
                ],
            },
            {
                "id": "workflow-product-feedback",
                "org_id": org_id,
                "kind": "meeting_action_items",
                "status": "needs_review",
                "input_text": (
                    "Sarah: I will update the product roadmap in Notion by next Monday.\n"
                    "Anish: I will schedule 3 user interviews."
                ),
                "destination": "manual",
                "data_tier": "normal",
                "model_route": "gemini-2.0-flash",
                "created_at": datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=6),
                "action_items": [
                    {
                        "title": "Update the product roadmap in Notion",
                        "owner": "sarah@osai.local",
                        "due_date": "2026-06-08",
                        "source_quote": (
                            "Sarah: I will update the product roadmap in Notion by next Monday."
                        ),
                        "destination": "notion",
                        "confidence": 0.94,
                        "status": "needs_review",
                    },
                    {
                        "title": "Schedule 3 user interviews",
                        "owner": "anish@osai.local",
                        "due_date": "2026-06-12",
                        "source_quote": "Anish: I will schedule 3 user interviews.",
                        "destination": "slack",
                        "confidence": 0.91,
                        "status": "needs_review",
                    },
                ],
            },
            {
                "id": "workflow-vpc-deployment",
                "org_id": org_id,
                "kind": "meeting_action_items",
                "status": "completed",
                "input_text": (
                    "Yash: I will map VPC security groups for Ollama services.\n"
                    "Anish: I will review."
                ),
                "destination": "manual",
                "data_tier": "amber",
                "model_route": "gemini-2.0-flash",
                "created_at": (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=18)),
                "action_items": [
                    {
                        "title": "Map VPC security groups for Ollama services",
                        "owner": "yash@osai.local",
                        "due_date": "2026-06-09",
                        "source_quote": (
                            "Yash: I will map VPC security groups for Ollama services."
                        ),
                        "destination": "google_drive",
                        "confidence": 0.89,
                        "status": "executed",
                        "external_url": "https://drive.google.com/file/d/vpc-map-123",
                        "executed_at": (
                            datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=14)
                        ),
                    }
                ],
            },
            {
                "id": "workflow-sprint-retro",
                "org_id": org_id,
                "kind": "meeting_action_items",
                "status": "needs_review",
                "input_text": (
                    "Ishika: I will clean up the sprint planning board.\n"
                    "Sarah: I will perform the database migration."
                ),
                "destination": "manual",
                "data_tier": "normal",
                "model_route": "gemini-2.0-flash",
                "created_at": datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1),
                "action_items": [
                    {
                        "title": "Clean up the sprint planning board",
                        "owner": "ishika@osai.local",
                        "due_date": "2026-06-12",
                        "source_quote": "Ishika: I will clean up the sprint planning board.",
                        "destination": "notion",
                        "confidence": 0.97,
                        "status": "needs_review",
                    },
                    {
                        "title": "Perform the database migration",
                        "owner": "sarah@osai.local",
                        "due_date": "2026-06-10",
                        "source_quote": "Sarah: I will perform the database migration.",
                        "destination": "manual",
                        "confidence": 0.93,
                        "status": "needs_review",
                    },
                ],
            },
            {
                "id": "workflow-security-audit",
                "org_id": org_id,
                "kind": "meeting_action_items",
                "status": "completed",
                "input_text": (
                    "Yash: I will encrypt all Red-tier databases "
                    "on local Qdrant by Wednesday.\n"
                    "Anish: I will configure the SSL certificates."
                ),
                "destination": "manual",
                "data_tier": "red",
                "model_route": "llama3",
                "created_at": datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1),
                "action_items": [
                    {
                        "title": "Encrypt all Red-tier databases on local Qdrant",
                        "owner": "yash@osai.local",
                        "due_date": "2026-06-10",
                        "source_quote": (
                            "Yash: I will encrypt all Red-tier "
                            "databases on local Qdrant by Wednesday."
                        ),
                        "destination": "freshdesk",
                        "confidence": 0.88,
                        "status": "executed",
                        "external_url": "https://freshdesk.com/tickets/101",
                        "executed_at": (
                            datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=12)
                        ),
                    }
                ],
            },
            {
                "id": "workflow-marketing-strategy",
                "org_id": org_id,
                "kind": "meeting_action_items",
                "status": "failed",
                "input_text": "Ishika: I will send the proposal to the client.",
                "destination": "slack",
                "data_tier": "normal",
                "model_route": "gemini-2.0-flash",
                "created_at": datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=2),
                "action_items": [],
            },
        ]

        for r in runs_data:
            run = WorkflowRun(
                id=r["id"],
                org_id=r["org_id"],
                kind=r["kind"],
                status=r["status"],
                input_text=r["input_text"],
                destination=r["destination"],
                data_tier=r["data_tier"],
                model_route=r["model_route"],
                created_at=r["created_at"],
            )
            session.add(run)
            session.flush()
            for item in r["action_items"]:
                ai = ActionItemRecord(
                    id=str(uuid4()),
                    workflow_run_id=r["id"],
                    title=item["title"],
                    owner=item["owner"],
                    due_date=item["due_date"],
                    destination=item["destination"],
                    source_quote=item["source_quote"],
                    confidence=item["confidence"],
                    status=item["status"],
                    external_url=item.get("external_url"),
                    executed_at=item.get("executed_at"),
                    created_at=r["created_at"],
                )
                session.add(ai)

    # Seed Mock Ingestion Sync Runs
    if session.query(SyncRun).count() == 0:
        syncs = [
            {
                "connector_key": "notion",
                "status": "succeeded",
                "documents_seen": 14,
                "documents_indexed": 12,
                "error": None,
                "started_at": (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=4)),
                "finished_at": (
                    datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=3, minutes=55)
                ),
            },
            {
                "connector_key": "slack",
                "status": "succeeded",
                "documents_seen": 45,
                "documents_indexed": 45,
                "error": None,
                "started_at": (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)),
                "finished_at": (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)),
            },
            {
                "connector_key": "freshdesk",
                "status": "failed",
                "documents_seen": 0,
                "documents_indexed": 0,
                "error": "Invalid API credentials provided",
                "started_at": (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)),
                "finished_at": (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)),
            },
            {
                "connector_key": "google_drive",
                "status": "succeeded",
                "documents_seen": 8,
                "documents_indexed": 8,
                "error": None,
                "started_at": (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=8)),
                "finished_at": (
                    datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=7, minutes=52)
                ),
            },
            {
                "connector_key": "slack",
                "status": "succeeded",
                "documents_seen": 112,
                "documents_indexed": 110,
                "error": None,
                "started_at": (
                    datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=30)
                ),
                "finished_at": (
                    datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=28)
                ),
            },
            {
                "connector_key": "notion",
                "status": "succeeded",
                "documents_seen": 5,
                "documents_indexed": 5,
                "error": None,
                "started_at": (
                    datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=15)
                ),
                "finished_at": (
                    datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=14)
                ),
            },
            {
                "connector_key": "freshdesk",
                "status": "succeeded",
                "documents_seen": 12,
                "documents_indexed": 12,
                "error": None,
                "started_at": (datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=5)),
                "finished_at": (
                    datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=4)
                ),
            },
        ]
        for s in syncs:
            sr = SyncRun(
                id=str(uuid4()),
                org_id=org_id,
                connector_key=s["connector_key"],
                status=s["status"],
                documents_seen=s["documents_seen"],
                documents_indexed=s["documents_indexed"],
                error=s["error"],
                started_at=s["started_at"],
                finished_at=s["finished_at"],
            )
            session.add(sr)

    # Seed Mock Source Documents & Chunks for RAG Search
    if session.query(SourceDocumentRecord).count() == 0:
        docs = _get_mock_docs(org_id)
        for d in docs:
            doc = SourceDocumentRecord(
                id=d["id"],
                org_id=org_id,
                source_type=d["source_type"],
                external_id=d["external_id"],
                title=d["title"],
                text=d["text"],
                metadata_json={"title": d["title"]},
                permissions=["source:all"],
                data_tier="normal",
                ingested_at=datetime.datetime.now(datetime.UTC),
            )
            session.add(doc)
            session.flush()

            chunk = Chunk(
                id=f"chunk-{d['id']}",
                source_document_id=d["id"],
                org_id=org_id,
                source_type=d["source_type"],
                chunk_index=0,
                text=d["text"],
                content_preview=d["text"][:100] + "...",
                permissions=["source:all"],
                data_tier="normal",
                metadata_json={"title": d["title"]},
            )
            session.add(chunk)

    session.add(AuditEvent(org_id=org_id, event_type="seed.rich_demo_data", actor="system"))
    session.commit()


def list_integrations(session: Session, org_id: str) -> list[dict[str, object]]:
    rows = session.execute(
        select(ConnectorRecord, ConnectorAccount)
        .join(
            ConnectorAccount,
            (ConnectorAccount.connector_key == ConnectorRecord.key)
            & (ConnectorAccount.org_id == org_id),
            isouter=True,
        )
        .order_by(ConnectorRecord.display_name)
    ).all()
    # Dedupe by connector key (a stray duplicate ConnectorAccount must never
    # render as two cards); prefer the connected account.
    by_key: dict[str, dict[str, object]] = {}
    for connector, account in rows:
        cfg = (account.config or {}) if account else {}
        entry = {
            "key": connector.key,
            "display_name": connector.display_name,
            "capabilities": connector.capabilities,
            "auth_state": account.auth_state if account else "not_configured",
            "scopes": account.scopes if account else [],
            "last_sync": (
                utc_iso(account.last_sync_at) if account and account.last_sync_at else None
            ),
            "sync_error": account.last_error if account else None,
            "account_email": cfg.get("account_email"),
            "previous_account_email": cfg.get("previous_account_email"),
            "last_reconnected_at": cfg.get("last_reconnected_at"),
        }
        existing = by_key.get(connector.key)
        if existing is None or (
            entry["auth_state"] == "connected" and existing["auth_state"] != "connected"
        ):
            by_key[connector.key] = entry
    return list(by_key.values())


def upsert_source_documents(session: Session, documents: list[SourceDocument]) -> int:
    indexed = 0
    for document in documents:
        record = session.get(SourceDocumentRecord, document.source_id)
        # Cross-tenant overwrite guard: document ids are keyed by the external
        # resource (e.g. "notion:<page_id>"), not the org. If two orgs connect the
        # same underlying resource, a later sync must not silently reassign an
        # existing row to a different org — that would overwrite (or hijack) the
        # first org's document. Skip and log instead (SEC-006).
        if record is not None and record.org_id != document.org_id:
            logger.warning(
                "Skipping document %s: already owned by org %s, not %s",
                document.source_id,
                record.org_id,
                document.org_id,
            )
            continue
        values = {
            "org_id": document.org_id,
            "source_type": document.source_type,
            "external_id": document.external_id,
            "title": document.title,
            "url": document.url,
            "author": document.author,
            "text": document.text,
            "metadata_json": document.metadata,
            "permissions": document.permissions,
            "data_tier": document.data_tier,
            "department_id": document.department_id,
            "source_created_at": document.created_at,
            "source_updated_at": document.updated_at,
            "ingested_at": now_utc(),
        }
        if record is None:
            session.add(SourceDocumentRecord(id=document.source_id, **values))
        else:
            for key, value in values.items():
                setattr(record, key, value)

        # The session is autoflush=False, so flush the parent document now to
        # guarantee its row exists before we insert child chunks (otherwise the
        # chunk FK to source_documents fails on a fresh sync).
        session.flush()

        session.query(Chunk).filter(Chunk.source_document_id == document.source_id).delete()
        for chunk in chunk_document(document):
            session.add(
                Chunk(
                    id=str(chunk["chunk_id"]),
                    source_document_id=document.source_id,
                    org_id=document.org_id,
                    source_type=document.source_type,
                    chunk_index=int(chunk["chunk_index"]),
                    text=str(chunk["text"]),
                    content_preview=str(chunk["content_preview"]),
                    permissions=document.permissions,
                    data_tier=document.data_tier,
                    metadata_json=dict(chunk["metadata"]),
                )
            )
        indexed += 1

    # Phase 4: mirror ingested documents into the org's gbrain (per-org home)
    # so the knowledge graph self-wires from real content. Inert unless
    # OSAI_GBRAIN_HOME is configured; never blocks or fails ingestion.
    if documents:
        try:
            from memory.gbrain_client import mirror_documents

            by_org: dict[str, list[SourceDocument]] = {}
            for d in documents:
                by_org.setdefault(d.org_id, []).append(d)
            for org_id, docs in by_org.items():
                mirror_documents(org_id, docs)
        except Exception:  # noqa: BLE001 — best-effort sidecar mirror
            pass

    return indexed


def chunks_for_documents(documents: list[SourceDocument]) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    for document in documents:
        chunks.extend(chunk_document(document))
    return chunks


def record_sync_result(
    session: Session,
    *,
    org_id: str,
    connector_key: str,
    status: str,
    documents_seen: int,
    documents_indexed: int,
    error: str | None = None,
) -> SyncRun:
    # sync_runs (and the connector_accounts row updated below) FK to
    # connectors.key; ensure it exists for Composio-only apps (gmail, …).
    ensure_connector_record(session, connector_key, capabilities=["sync", "search"])
    run = SyncRun(
        org_id=org_id,
        connector_key=connector_key,
        status=status,
        documents_seen=documents_seen,
        documents_indexed=documents_indexed,
        error=error,
        finished_at=now_utc(),
    )
    session.add(run)
    account = session.scalar(
        select(ConnectorAccount).where(
            ConnectorAccount.org_id == org_id,
            ConnectorAccount.connector_key == connector_key,
        )
    )
    if account:
        account.auth_state = "connected" if status != "failed" else account.auth_state
        account.last_sync_at = now_utc()
        account.last_error = error
    session.add(
        AuditEvent(
            org_id=org_id,
            event_type="connector.sync",
            actor="system",
            payload={
                "connector_key": connector_key,
                "status": status,
                "documents_seen": documents_seen,
                "documents_indexed": documents_indexed,
                "error": error,
            },
        )
    )
    session.commit()
    return run


def _require_active_principal(session: Session, claims: dict | None) -> User | None:
    """Resolve the authenticated user behind a token, or None for system/demo
    context (a token with no `sub`).

    A token that carries a `sub` whose user row no longer exists is a *stale
    principal* — e.g. the user deleted their account but kept the 30-day JWT.
    Such a token must be rejected, not treated as system context: the governance
    filter reads an empty permission set as "see everything" and clearance would
    otherwise fall through to "red", so silently degrading here is a
    privilege-escalation hole (SEC-002). Fail closed with 401 instead."""
    user_id = claims.get("sub") if claims else None
    if not user_id:
        return None
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Session is no longer valid; sign in again.")
    if claims.get("org_id") != user.org_id:
        raise HTTPException(
            status_code=401,
            detail="Session workspace membership changed; sign in again.",
        )
    # Token revocation: a token minted before the user's current generation
    # (deleted account, sign-out-everywhere, forced rotation) carries a stale
    # `tv` and is rejected even though the signature is still valid (SEC-002).
    if claims.get("tv", 0) != (user.token_version or 0):
        raise HTTPException(status_code=401, detail="Session has been revoked; sign in again.")
    return user


def assert_token_current(session: Session, claims: dict | None) -> None:
    """Raise 401 if the token is for a deleted or revoked principal. For auth
    paths (e.g. require_admin) that verify a session without needing the user's
    permission grants. No-op for system/demo context (a token with no `sub`)."""
    _require_active_principal(session, claims)


def user_permissions(session: Session, claims: dict | None) -> list[str]:
    """Resolve the caller's permission grants from their verified JWT claims, so
    org-scoped reads can be filtered to what that user is actually allowed to see.
    Returns [] when there's no authenticated user (e.g. the public demo path),
    which the governance filter treats as system/admin context over demo data."""
    user = _require_active_principal(session, claims)
    if user is None:
        return []
    grants = list(user.permissions or [])
    # Implicit identity grants: every signed-in member can see documents shared
    # with them personally ("user:<id>") or with their department ("dept:<id>").
    grants.append(f"user:{user.id}")
    if user.department_id:
        grants.append(f"dept:{user.department_id}")
    return grants


# Data-clearance tiers, ordered least→most sensitive. A member may see a document
# whose tier is at or below their clearance; admins always see everything.
TIER_ORDER: dict[str, int] = {"normal": 0, "amber": 1, "red": 2}


def user_clearance(session: Session, claims: dict | None) -> str:
    """The caller's data-clearance tier. Admins (and system/demo context with no
    authenticated user) get 'red' = see-all; otherwise the member's own tier.
    A stale principal (deleted account, live token) is rejected — see
    _require_active_principal (SEC-002)."""
    user = _require_active_principal(session, claims)
    if user is None:
        return "red"
    if user.role == "admin":
        return "red"
    return user.data_tier or "normal"


def current_org_actor(
    session: Session, org_id: str, claims: dict | None
) -> tuple[str | None, bool]:
    """Return the current DB actor id and admin status for one organization.

    JWT roles are sign-in-time snapshots. Authorization of tenant resources and
    connector side effects must use the user's current DB role so a demotion is
    effective immediately. Missing, deleted, and cross-org principals fail closed.
    """
    user_id = claims.get("sub") if claims else None
    user = session.get(User, user_id) if user_id else None
    if user is None or user.org_id != org_id:
        return None, False
    return user.id, user.role == "admin"


# Proposed agent actions are persisted so a "confirm" can succeed even if a
# different web worker (or the same process after a restart/cold-start) handles
# it — an in-process dict alone loses them. Stored in connector_actions with
# status="proposed"; the full execution descriptor lives in the payload.
_PROPOSED_TTL_HOURS = 24


def _ensure_connector_record(
    session: Session,
    connector_key: str,
    *,
    capabilities: list[str],
) -> None:
    """Satisfy the action/account foreign key even on a fresh, unseeded DB.

    Provider catalogs can introduce connector keys dynamically. A savepoint
    makes concurrent first use safe: if another transaction inserts the same
    key first, only the nested insert rolls back and the caller can continue.
    """
    if session.get(ConnectorRecord, connector_key) is not None:
        return
    try:
        with session.begin_nested():
            session.add(
                ConnectorRecord(
                    key=connector_key,
                    display_name=connector_key.replace("_", " ").title(),
                    capabilities=capabilities,
                )
            )
            session.flush()
    except IntegrityError:
        # The unique key was created by a concurrent request.
        pass


def save_proposed_action(action_id: str, descriptor: dict) -> None:
    with SessionLocal() as session:
        if session.get(ConnectorAction, action_id) is not None:
            return
        connector_key = str(descriptor.get("tool") or "unknown")
        _ensure_connector_record(session, connector_key, capabilities=["execute"])
        session.add(
            ConnectorAction(
                id=action_id,
                org_id=descriptor.get("org_id", ""),
                connector_key=connector_key,
                action_type=descriptor.get("action", ""),
                status="proposed",
                payload=descriptor,
            )
        )
        session.commit()


def load_action_for_resolution(action_id: str) -> tuple[str, dict | None]:
    """Load immutable ownership metadata for confirm/dismiss authorization."""
    try:
        with SessionLocal() as session:
            row = session.get(ConnectorAction, action_id)
            if row is None:
                return "absent", None
            if row.status == "proposed":
                created_at = row.created_at
                if created_at is None:
                    return "expired", dict(row.payload or {})
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
                else:
                    created_at = created_at.astimezone(UTC)
                if now_utc() - created_at > timedelta(hours=_PROPOSED_TTL_HOURS):
                    return "expired", dict(row.payload or {})
            return row.status, dict(row.payload or {})
    except SQLAlchemyError:
        return "unavailable", None


def claim_proposed_action(action_id: str) -> str:
    """Atomically claim a proposed action so exactly one confirm can execute it.

    Returns "claimed" (this caller won the race and may execute), "taken" (a
    concurrent or prior confirm already consumed it), "expired" (older than the
    approval TTL), "absent" (no durable row), or "unavailable" (the durable
    store could not be reached).

    The single `UPDATE ... WHERE status='proposed' AND created_at >= cutoff` is
    the guard: under READ COMMITTED two concurrent confirms serialize on the
    row, so the loser matches zero rows. This prevents stale or double-executed
    connector side effects: duplicate tickets, pages, or messages (SEC-007)."""
    try:
        with SessionLocal() as session:
            row = session.get(ConnectorAction, action_id)
            if row is None:
                return "absent"
            if row.status != "proposed":
                return "taken"
            # connector_actions.created_at is a timezone-naive database column.
            # Bind a naive UTC cutoff so SQLite and PostgreSQL enforce the same
            # TTL in the atomic execution claim.
            cutoff = (now_utc() - timedelta(hours=_PROPOSED_TTL_HOURS)).replace(tzinfo=None)
            created_at = row.created_at
            if created_at is not None and created_at.tzinfo is not None:
                created_at = created_at.astimezone(UTC).replace(tzinfo=None)
            expired = created_at is None or created_at < cutoff
            updated = (
                session.query(ConnectorAction)
                .filter(
                    ConnectorAction.id == action_id,
                    ConnectorAction.status == "proposed",
                    ConnectorAction.created_at >= cutoff,
                )
                .update({"status": "consumed"}, synchronize_session=False)
            )
            session.commit()
            if updated == 1:
                return "claimed"
            return "expired" if expired else "taken"
    except SQLAlchemyError:
        # A real external side effect must never execute without the durable
        # single-use guard.
        return "unavailable"


def dismiss_proposed_action(action_id: str) -> str:
    """Atomically revoke a proposal, mutually exclusive with confirmation."""
    try:
        with SessionLocal() as session:
            updated = (
                session.query(ConnectorAction)
                .filter(
                    ConnectorAction.id == action_id,
                    ConnectorAction.status == "proposed",
                )
                .update({"status": "dismissed"}, synchronize_session=False)
            )
            session.commit()
            if updated == 1:
                return "dismissed"
            row = session.get(ConnectorAction, action_id)
            if row is None:
                return "absent"
            return "already_dismissed" if row.status == "dismissed" else "taken"
    except SQLAlchemyError:
        return "unavailable"


def discard_proposed_action(action_id: str) -> None:
    with SessionLocal() as session:
        row = session.get(ConnectorAction, action_id)
        if row is not None:
            row.status = "consumed"
            session.commit()


def ensure_connector_record(
    session: Session,
    connector_key: str,
    *,
    capabilities: list[str] | None = None,
) -> None:
    """Ensure a `connectors` row exists for `connector_key`.

    connector_accounts, sync_runs, and connector_actions all FK to
    connectors.key. Under Composio-first, connector_key is an arbitrary app slug
    (gmail, linear, …) that was never seeded into `connectors`, so writing any of
    those rows for such an app raised a ForeignKeyViolation — which silently
    failed sync and disconnect. Create a minimal, concurrency-safe record on
    demand."""
    _ensure_connector_record(
        session,
        connector_key,
        capabilities=capabilities or ["execute"],
    )


def ensure_connector_account(session: Session, org_id: str, connector_key: str) -> ConnectorAccount:
    """Get (or create) the ConnectorAccount row for an org+connector. A Composio
    OAuth connection may not have created one, but we need it to persist the
    connected-account identity used for reconnect handling."""
    ensure_connector_record(session, connector_key, capabilities=["sync", "search"])
    account = session.scalar(
        select(ConnectorAccount).where(
            ConnectorAccount.org_id == org_id,
            ConnectorAccount.connector_key == connector_key,
        )
    )
    if account is None:
        account = ConnectorAccount(org_id=org_id, connector_key=connector_key)
        session.add(account)
        session.flush()
    return account


def purge_source_type(session: Session, org_id: str, source_type: str) -> int:
    """Delete every source document (and its chunks) for one connector in an org.
    Used when a connector is reconnected with a different account so the previous
    account's files no longer appear in counts or retrieval. Returns rows removed.

    Note: the caller is responsible for deleting the matching Qdrant vectors."""
    doc_ids = session.scalars(
        select(SourceDocumentRecord.id).where(
            SourceDocumentRecord.org_id == org_id,
            SourceDocumentRecord.source_type == source_type,
        )
    ).all()
    if not doc_ids:
        return 0
    session.query(Chunk).filter(Chunk.org_id == org_id, Chunk.source_type == source_type).delete(
        synchronize_session=False
    )
    session.query(SourceDocumentRecord).filter(SourceDocumentRecord.id.in_(doc_ids)).delete(
        synchronize_session=False
    )
    session.flush()
    return len(doc_ids)


def list_sync_runs(session: Session, org_id: str, limit: int = 50) -> Sequence[SyncRun]:
    return session.scalars(
        select(SyncRun)
        .where(SyncRun.org_id == org_id)
        .order_by(desc(SyncRun.started_at), desc(SyncRun.id))
        .limit(limit)
    ).all()


def sync_run_page(
    session: Session,
    org_id: str,
    *,
    limit: int,
    cursor: str | None = None,
) -> tuple[Sequence[SyncRun], str | None, dict[str, object]]:
    """Return one stable cursor page plus all-time org aggregates."""
    stmt = select(SyncRun).where(SyncRun.org_id == org_id)
    if cursor:
        boundary = session.scalar(
            select(SyncRun).where(SyncRun.org_id == org_id, SyncRun.id == cursor)
        )
        if boundary is None:
            raise LookupError("Invalid sync-run cursor")
        stmt = stmt.where(
            or_(
                SyncRun.started_at < boundary.started_at,
                and_(
                    SyncRun.started_at == boundary.started_at,
                    SyncRun.id < boundary.id,
                ),
            )
        )

    rows = list(
        session.scalars(
            stmt.order_by(desc(SyncRun.started_at), desc(SyncRun.id)).limit(limit + 1)
        ).all()
    )
    items = rows[:limit]
    next_cursor = items[-1].id if len(rows) > limit else None

    grouped = session.execute(
        select(
            SyncRun.connector_key,
            SyncRun.status,
            func.count(SyncRun.id),
            func.coalesce(func.sum(SyncRun.documents_seen), 0),
            func.coalesce(func.sum(SyncRun.documents_indexed), 0),
        )
        .where(SyncRun.org_id == org_id)
        .group_by(SyncRun.connector_key, SyncRun.status)
    ).all()
    status_counts: dict[str, int] = {}
    by_connector: dict[str, dict[str, object]] = {}
    total_seen = 0
    total_indexed = 0
    for connector_key, status, count, seen, indexed in grouped:
        count = int(count)
        seen = int(seen)
        indexed = int(indexed)
        status_counts[str(status)] = status_counts.get(str(status), 0) + count
        total_seen += seen
        total_indexed += indexed
        connector = by_connector.setdefault(
            str(connector_key),
            {
                "total_runs": 0,
                "status_counts": {},
                "documents_seen": 0,
                "documents_indexed": 0,
            },
        )
        connector["total_runs"] = int(connector["total_runs"]) + count
        connector_statuses = connector["status_counts"]
        assert isinstance(connector_statuses, dict)
        connector_statuses[str(status)] = count
        connector["documents_seen"] = int(connector["documents_seen"]) + seen
        connector["documents_indexed"] = int(connector["documents_indexed"]) + indexed

    return (
        items,
        next_cursor,
        {
            "total_runs": sum(status_counts.values()),
            "status_counts": status_counts,
            "documents_seen": total_seen,
            "documents_indexed": total_indexed,
            "by_connector": by_connector,
        },
    )


def list_workflow_runs(session: Session, org_id: str, limit: int = 50) -> Sequence[WorkflowRun]:
    return session.scalars(
        select(WorkflowRun)
        .where(WorkflowRun.org_id == org_id)
        .order_by(desc(WorkflowRun.created_at))
        .limit(limit)
    ).all()


def list_visible_workflow_runs(
    session: Session,
    org_id: str,
    *,
    viewer_user_id: str | None,
    viewer_is_admin: bool,
    limit: int = 50,
) -> Sequence[WorkflowRun]:
    """Workflow runs visible to one current principal.

    Creators see their own runs; current admins see every run in the org. Rows
    predating ``created_by`` have NULL ownership and are therefore admin-only.
    """
    if not viewer_is_admin and not viewer_user_id:
        return []
    stmt = select(WorkflowRun).where(WorkflowRun.org_id == org_id)
    if not viewer_is_admin:
        stmt = stmt.where(WorkflowRun.created_by == viewer_user_id)
    return session.scalars(stmt.order_by(desc(WorkflowRun.created_at)).limit(limit)).all()


def try_db[T](_operation: str, fallback: T, fn) -> T:
    try:
        return fn()
    except SQLAlchemyError:
        return fallback


# ---------------------------------------------------------------------------
# Workflow run persistence
# ---------------------------------------------------------------------------


def save_workflow_run(
    session: Session,
    *,
    run_id: str,
    org_id: str,
    created_by: str | None,
    kind: str,
    status: str,
    input_text: str,
    destination: str,
    data_tier: str,
    model_route: str | None,
    items: list[dict],
) -> None:
    """Persist a WorkflowRun and its ActionItemRecords in one commit."""
    session.add(
        WorkflowRun(
            id=run_id,
            org_id=org_id,
            created_by=created_by,
            kind=kind,
            status=status,
            input_text=input_text,
            destination=destination,
            data_tier=data_tier,
            model_route=model_route,
        )
    )
    for item in items:
        session.add(
            ActionItemRecord(
                workflow_run_id=run_id,
                title=item.get("title", ""),
                owner=item.get("owner"),
                due_date=item.get("due_date"),
                source_quote=item.get("source_quote"),
                destination=item.get("destination", destination),
                confidence=float(item.get("confidence", 0.0)),
                status="needs_review",
            )
        )
    session.add(
        AuditEvent(
            org_id=org_id,
            event_type="workflow.created",
            actor=created_by or "system",
            payload={"run_id": run_id, "kind": kind, "destination": destination},
        )
    )
    session.commit()


def get_workflow_run(session: Session, run_id: str) -> dict | None:
    """Return a run dict with its action items, or None if not found."""
    run = session.get(WorkflowRun, run_id)
    if run is None:
        return None
    items = session.scalars(
        select(ActionItemRecord)
        .where(ActionItemRecord.workflow_run_id == run_id)
        .execution_options(populate_existing=True)
    ).all()
    return {
        "id": run.id,
        "org_id": run.org_id,
        "created_by": run.created_by,
        "kind": run.kind,
        "status": run.status,
        "input_text": run.input_text,
        "destination": run.destination,
        "data_tier": run.data_tier,
        "model_route": run.model_route,
        "created_at": utc_iso(run.created_at),
        "action_items": [
            {
                "id": item.id,
                "title": item.title,
                "owner": item.owner,
                "due_date": item.due_date,
                "source_quote": item.source_quote,
                "destination": item.destination,
                "confidence": item.confidence,
                "status": item.status,
                "external_url": item.external_url,
                "executed_at": utc_iso(item.executed_at) if item.executed_at else None,
            }
            for item in items
        ],
    }


# Only failures proven to happen before a provider call are retryable.
ACTION_ITEM_CLAIMABLE = ("needs_review", "failed_preflight")
ACTION_ITEM_EXECUTION_STALE_AFTER = timedelta(minutes=15)


def workflow_action_execution_key(item_id: str) -> str:
    """Stable UUID accepted by providers such as Slack's client_msg_id."""
    return str(uuid5(NAMESPACE_URL, f"osai://workflow-actions/{item_id}"))


def claim_action_item(session: Session, *, item_id: str, org_id: str, actor: str = "user") -> str:
    """Atomically claim an action item so exactly one approval can execute it.

    Returns "claimed", "unknown" for a stale ambiguous execution, "taken" for
    an active/prior execution, or "absent" when the tenant-scoped row is missing.

    The single `UPDATE ... WHERE status IN (claimable)` is the guard: under READ
    COMMITTED two concurrent approvals serialize on the row, so the loser matches
    zero rows. Without it, both callers read `needs_review`, both pass the check
    and both push to the connector — a duplicate ticket, page or message. This is
    the same guarantee claim_proposed_action gives the Ask confirm path (SEC-007);
    workflow approval executes the same connectors and needs it just as much.
    """
    item = session.scalar(
        select(ActionItemRecord)
        .join(WorkflowRun, WorkflowRun.id == ActionItemRecord.workflow_run_id)
        .where(ActionItemRecord.id == item_id, WorkflowRun.org_id == org_id)
    )
    if item is None:
        return "absent"
    stale_before = now_utc() - ACTION_ITEM_EXECUTION_STALE_AFTER
    stale = (
        session.query(ActionItemRecord)
        .filter(
            ActionItemRecord.id == item_id,
            ActionItemRecord.workflow_run_id == item.workflow_run_id,
            ActionItemRecord.status == "executing",
            or_(
                ActionItemRecord.execution_started_at.is_(None),
                ActionItemRecord.execution_started_at <= stale_before,
            ),
        )
        .update(
            {"status": "outcome_unknown", "executed_at": now_utc()},
            synchronize_session="fetch",
        )
    )
    if stale == 1:
        session.add(
            AuditEvent(
                org_id=org_id,
                event_type="action_item.outcome_unknown",
                actor="system",
                payload={"item_id": item_id, "reason": "stale_execution_claim"},
            )
        )
        session.commit()
        return "unknown"
    updated = (
        session.query(ActionItemRecord)
        .filter(
            ActionItemRecord.id == item_id,
            ActionItemRecord.workflow_run_id == item.workflow_run_id,
            ActionItemRecord.status.in_(ACTION_ITEM_CLAIMABLE),
        )
        .update(
            {
                "status": "executing",
                "execution_key": workflow_action_execution_key(item_id),
                "execution_started_at": now_utc(),
                "executed_at": None,
            },
            synchronize_session="fetch",
        )
    )
    if updated != 1:
        session.rollback()
        return "taken"
    session.add(
        AuditEvent(
            org_id=org_id,
            event_type="action_item.claimed",
            actor=actor,
            payload={"item_id": item_id, "destination": item.destination},
        )
    )
    session.commit()
    return "claimed"


def cancel_action_item(session: Session, *, item_id: str, org_id: str, actor: str = "user") -> str:
    """Reject an item that is awaiting review, so it stops asking to be run."""
    item = session.scalar(
        select(ActionItemRecord)
        .join(WorkflowRun, WorkflowRun.id == ActionItemRecord.workflow_run_id)
        .where(ActionItemRecord.id == item_id, WorkflowRun.org_id == org_id)
    )
    if item is None:
        return "absent"
    stale_before = now_utc() - ACTION_ITEM_EXECUTION_STALE_AFTER
    stale = (
        session.query(ActionItemRecord)
        .filter(
            ActionItemRecord.id == item_id,
            ActionItemRecord.workflow_run_id == item.workflow_run_id,
            ActionItemRecord.status == "executing",
            or_(
                ActionItemRecord.execution_started_at.is_(None),
                ActionItemRecord.execution_started_at <= stale_before,
            ),
        )
        .update(
            {"status": "outcome_unknown", "executed_at": now_utc()},
            synchronize_session="fetch",
        )
    )
    if stale == 1:
        session.add(
            AuditEvent(
                org_id=org_id,
                event_type="action_item.outcome_unknown",
                actor="system",
                payload={"item_id": item_id, "reason": "stale_execution_claim"},
            )
        )
        session.commit()
        return "unknown"
    updated = (
        session.query(ActionItemRecord)
        .filter(
            ActionItemRecord.id == item_id,
            ActionItemRecord.workflow_run_id == item.workflow_run_id,
            ActionItemRecord.status.in_(ACTION_ITEM_CLAIMABLE),
        )
        .update({"status": "cancelled"}, synchronize_session="fetch")
    )
    session.commit()
    if updated != 1:
        return "taken"
    session.add(
        AuditEvent(
            org_id=org_id,
            event_type="action_item.cancelled",
            actor=actor,
            payload={"item_id": item_id},
        )
    )
    session.commit()
    return "cancelled"


def approve_action_item(
    session: Session,
    *,
    item_id: str,
    org_id: str,
    actor: str = "user",
) -> ActionItemRecord | None:
    """Record the approval of an already-claimed action item.

    Callers must claim_action_item() first: this does not guard against a
    concurrent approval, it only writes the paperwork for one that won.
    """
    item = session.scalar(
        select(ActionItemRecord)
        .join(WorkflowRun, WorkflowRun.id == ActionItemRecord.workflow_run_id)
        .where(ActionItemRecord.id == item_id, WorkflowRun.org_id == org_id)
    )
    if item is None:
        return None
    if item.destination != "manual":
        execution_key = item.execution_key or workflow_action_execution_key(item_id)
        outbox_id = f"workflow-action:{execution_key}"
        outbox = session.get(ConnectorAction, outbox_id)
        payload = {
            "action_item_id": item_id,
            "title": item.title,
            "idempotency_key": execution_key,
        }
        if outbox is None:
            session.add(
                ConnectorAction(
                    id=outbox_id,
                    org_id=org_id,
                    connector_key=item.destination,
                    action_type="execute_action_item",
                    status="pending",
                    payload=payload,
                )
            )
        else:
            outbox.status = "pending"
            outbox.payload = payload
    session.add(
        AuditEvent(
            org_id=org_id,
            event_type="action_item.approved",
            actor=actor,
            payload={"item_id": item_id, "destination": item.destination},
        )
    )
    session.commit()
    return item


def update_action_item_execution(
    session: Session,
    *,
    item_id: str,
    org_id: str,
    status: str,
    external_url: str | None = None,
) -> bool:
    """Record the outcome of executing an action item."""
    from db.models import now_utc

    item = session.scalar(
        select(ActionItemRecord)
        .join(WorkflowRun, WorkflowRun.id == ActionItemRecord.workflow_run_id)
        .where(ActionItemRecord.id == item_id, WorkflowRun.org_id == org_id)
    )
    if item is None:
        return False
    if status not in {"completed", "failed_preflight", "outcome_unknown"}:
        raise ValueError(f"Unsupported action-item execution status: {status}")
    updated = (
        session.query(ActionItemRecord)
        .filter(
            ActionItemRecord.id == item_id,
            ActionItemRecord.workflow_run_id == item.workflow_run_id,
            ActionItemRecord.status == "executing",
        )
        .update(
            {
                "status": status,
                "external_url": external_url,
                "executed_at": now_utc(),
            },
            synchronize_session="fetch",
        )
    )
    if updated != 1:
        session.rollback()
        return False
    execution_key = item.execution_key or workflow_action_execution_key(item_id)
    outbox = session.get(ConnectorAction, f"workflow-action:{execution_key}")
    if outbox is not None:
        outbox.status = status
    session.add(
        AuditEvent(
            org_id=org_id,
            event_type=f"action_item.{status}",
            actor="system",
            payload={"item_id": item_id, "external_url": external_url},
        )
    )
    session.commit()
    return True


def provision_org(
    session: Session,
    *,
    name: str,
    admin_email: str,
    admin_name: str,
) -> tuple[Org, User]:
    """Provision a new organization, its admin user, and seed connector accounts."""
    admin_email = normalize_email(admin_email)
    try:
        existing_user = find_user_by_email(session, admin_email)
    except AmbiguousUserEmailError as exc:
        raise ValueError(
            "Multiple users share one email identity; resolve duplicate accounts first."
        ) from exc
    if existing_user is not None:
        raise ValueError("A user with that email already exists")

    # Create Org
    org = Org(name=name)
    session.add(org)
    session.flush()  # generates org.id

    # Create Admin User
    user = User(
        org_id=org.id,
        email=admin_email,
        display_name=admin_name,
        role="admin",
        permissions=["org:admin", "source:all"],
    )
    session.add(user)

    # New orgs start with no connector accounts — connect flows upsert them on
    # demand, and Integrations shows only configured connections plus the full
    # Composio catalog entry point.

    # New orgs start with no departments — the admin creates their own from the
    # Team page so the org chart reflects how they actually work, instead of five
    # generic guesses (Engineering/Sales/…) that rarely match.

    # Log audit event
    session.add(
        AuditEvent(
            org_id=org.id,
            event_type="org.provisioned",
            actor="system",
            payload={"org_name": name, "admin_email": admin_email},
        )
    )

    session.commit()
    return org, user


# --- Per-info data-tier classification -------------------------------------

VALID_TIERS = ("normal", "amber", "red")
_TIER_RANK = {"normal": 0, "amber": 1, "red": 2}


def get_tier_rules(session: Session, org_id: str, connector_key: str) -> list[dict]:
    """Return the per-info tier rules configured for a connector account."""
    account = session.scalar(
        select(ConnectorAccount).where(
            ConnectorAccount.org_id == org_id,
            ConnectorAccount.connector_key == connector_key,
        )
    )
    return list(account.tier_rules or []) if account else []


def set_tier_rules(
    session: Session, org_id: str, connector_key: str, rules: list[dict]
) -> list[dict]:
    """Validate and persist tier rules for a connector account (creating it if needed)."""
    clean: list[dict] = []
    for rule in rules:
        pattern = str(rule.get("pattern", "")).strip()
        tier = str(rule.get("tier", "")).strip().lower()
        if not pattern or tier not in VALID_TIERS:
            continue
        clean.append({"pattern": pattern, "tier": tier})

    account = session.scalar(
        select(ConnectorAccount).where(
            ConnectorAccount.org_id == org_id,
            ConnectorAccount.connector_key == connector_key,
        )
    )
    if account is None:
        account = ConnectorAccount(org_id=org_id, connector_key=connector_key)
        session.add(account)
    account.tier_rules = clean
    session.commit()
    return clean


def _document_haystack(document: SourceDocument) -> str:
    parts = [document.title or "", document.url or "", document.external_id or ""]
    path = document.metadata.get("path") or document.metadata.get("folder")
    if path:
        parts.append(str(path))
    return " ".join(parts).lower()


def apply_tier_rules(
    session: Session, org_id: str, connector_key: str, documents: list[SourceDocument]
) -> None:
    """Override each document's data_tier in place from the connector's tier rules.

    Most-specific match wins (longest matching pattern). A document keeps the
    connector's default tier when no rule matches.
    """
    rules = get_tier_rules(session, org_id, connector_key)
    if not rules:
        return
    # Longest pattern first so a specific folder beats a broad one.
    rules = sorted(rules, key=lambda r: len(r.get("pattern", "")), reverse=True)
    for document in documents:
        haystack = _document_haystack(document)
        for rule in rules:
            if rule["pattern"].lower() in haystack:
                document.data_tier = rule["tier"]
                break


def reset_org_content(session: Session, org_id: str) -> dict[str, int]:
    """Delete all ingested/derived content for an org (documents, chunks, sync
    runs, workflow runs + action items, org memory) while KEEPING the org, its
    users, and connector connections. Use to clear seed/demo data so a fresh
    re-sync repopulates only the customer's real data."""
    run_ids = [
        r[0] for r in session.query(WorkflowRun.id).filter(WorkflowRun.org_id == org_id).all()
    ]
    counts = {
        "chunks": session.query(Chunk).filter(Chunk.org_id == org_id).delete(),
        "documents": session.query(SourceDocumentRecord)
        .filter(SourceDocumentRecord.org_id == org_id)
        .delete(),
        "notifications": session.query(Notification)
        .filter(Notification.org_id == org_id, Notification.type == "document.shared")
        .delete(),
        "action_items": (
            session.query(ActionItemRecord)
            .filter(ActionItemRecord.workflow_run_id.in_(run_ids))
            .delete(synchronize_session=False)
            if run_ids
            else 0
        ),
        "workflow_runs": session.query(WorkflowRun).filter(WorkflowRun.org_id == org_id).delete(),
        "org_memory": session.query(OrgMemory).filter(OrgMemory.org_id == org_id).delete(),
        "sync_runs": session.query(SyncRun).filter(SyncRun.org_id == org_id).delete(),
    }
    session.commit()
    return counts


# --- Team: departments, invites, members -----------------------------------

# The only roles the system understands. permissions_for_role treats anything
# that isn't "admin" as a member, so an unvalidated role string doesn't just sit
# in the column: it silently strips admin rights (a typo'd "Admin" included).
VALID_ROLES = ("admin", "member")


def permissions_for_role(role: str) -> list[str]:
    """Map a role to data-access grants used by permission-aware retrieval."""
    if role == "admin":
        return ["org:admin", "source:all"]
    return ["source:all"]


def count_admins(session: Session, org_id: str) -> int:
    return session.query(User).filter(User.org_id == org_id, User.role == "admin").count()


def list_departments(session: Session, org_id: str) -> list[Department]:
    return (
        session.query(Department)
        .filter(Department.org_id == org_id)
        .order_by(Department.name)
        .all()
    )


def create_department(
    session: Session, org_id: str, name: str, color: str | None = None
) -> Department:
    dept = Department(org_id=org_id, name=name.strip(), color=color or "#6a4cf5")
    session.add(dept)
    session.commit()
    return dept


def _validated_department_id(
    session: Session, org_id: str, department_id: str | None
) -> str | None:
    if department_id is None:
        return None
    exists = session.scalar(
        select(Department.id).where(Department.id == department_id, Department.org_id == org_id)
    )
    if exists is None:
        raise HTTPException(
            status_code=422,
            detail="Department does not belong to this workspace.",
        )
    return department_id


def _lock_org_for_team_mutation(session: Session, org_id: str) -> bool:
    """Serialize invariants that span several rows in one workspace.

    PostgreSQL gets a row lock without a write. SQLite ignores ``FOR UPDATE``,
    so a no-op update acquires its database write lock before any invariant is
    read. This keeps the repository functions safe in local/test SQLite too.
    """
    if session.get_bind().dialect.name == "sqlite":
        result = session.execute(update(Org).where(Org.id == org_id).values(name=Org.name))
        return result.rowcount == 1
    return session.scalar(select(Org.id).where(Org.id == org_id).with_for_update()) is not None


def update_department(
    session: Session, org_id: str, department_id: str, name: str
) -> Department | None:
    if not _lock_org_for_team_mutation(session, org_id):
        return None
    dept = session.scalar(
        select(Department).where(Department.id == department_id, Department.org_id == org_id)
    )
    if dept is None:
        return None
    dept.name = name.strip()
    session.commit()
    return dept


def delete_department(session: Session, org_id: str, department_id: str) -> bool:
    if not _lock_org_for_team_mutation(session, org_id):
        return False
    dept = session.scalar(
        select(Department).where(Department.id == department_id, Department.org_id == org_id)
    )
    if dept is None:
        return False
    in_use = any(
        session.scalar(statement.limit(1)) is not None
        for statement in (
            select(User.id).where(User.org_id == org_id, User.department_id == department_id),
            select(Invite.id).where(
                Invite.org_id == org_id,
                Invite.department_id == department_id,
                Invite.status == "pending",
            ),
            select(SourceDocumentRecord.id).where(
                SourceDocumentRecord.org_id == org_id,
                SourceDocumentRecord.department_id == department_id,
            ),
        )
    )
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=(
                "This department is still assigned to a member, invitation, or "
                "document. Reassign those items before deleting it."
            ),
        )
    # Historical invites are no longer actionable, so retain the record while
    # detaching its optional department before the tenant-scoped FK blocks delete.
    session.query(Invite).filter(
        Invite.org_id == org_id,
        Invite.department_id == department_id,
    ).update({Invite.department_id: None}, synchronize_session=False)
    session.delete(dept)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "This department was assigned while it was being deleted. "
                "Reassign those items and try again."
            ),
        ) from exc
    return True


def list_members(session: Session, org_id: str) -> list[User]:
    return session.query(User).filter(User.org_id == org_id).order_by(User.created_at).all()


def _member_transfer_counts(session: Session, org_id: str, user_id: str) -> dict[str, int]:
    """Count records where the user id grants access or lifecycle control.

    Authorship/provenance rows (thread turns, feedback, Ask reservations) and
    private-memory audience ids are deliberately excluded: changing those ids
    would make the successor appear to have performed the former member's work.
    """
    owned_threads = session.query(Thread).filter(
        Thread.org_id == org_id, Thread.created_by == user_id
    )
    return {
        "automations": session.query(Automation)
        .filter(Automation.org_id == org_id, Automation.user_id == user_id)
        .count(),
        "private_threads": owned_threads.filter(Thread.shared.is_(False)).count(),
        "shared_threads": owned_threads.filter(Thread.shared.is_(True)).count(),
        "workflow_runs": session.query(WorkflowRun)
        .filter(WorkflowRun.org_id == org_id, WorkflowRun.created_by == user_id)
        .count(),
    }


def _member_removal_blockers(session: Session, org_id: str, user_id: str) -> dict[str, int]:
    owned_uploads = 0
    document_access_grants = 0
    grant = f"user:{user_id}"
    documents = (
        session.query(
            SourceDocumentRecord.metadata_json,
            SourceDocumentRecord.permissions,
        )
        .filter(SourceDocumentRecord.org_id == org_id)
        .yield_per(500)
    )
    for metadata, permissions in documents:
        if (metadata or {}).get("uploader_id") == user_id:
            owned_uploads += 1
        elif grant in (permissions or []):
            document_access_grants += 1

    pending_connector_actions = sum(
        1
        for (payload,) in session.query(ConnectorAction.payload)
        .filter(
            ConnectorAction.org_id == org_id,
            ConnectorAction.status == "proposed",
        )
        .yield_per(200)
        if (payload or {}).get("user_id") == user_id
    )
    return {
        "owned_uploads": owned_uploads,
        "document_access_grants": document_access_grants,
        "private_memories": session.query(OrgMemory)
        .filter(OrgMemory.org_id == org_id, OrgMemory.user_id == user_id)
        .count(),
        "ask_exchanges": session.query(AskExchange)
        .filter(AskExchange.org_id == org_id, AskExchange.user_id == user_id)
        .count(),
        "pending_connector_actions": pending_connector_actions,
    }


def get_member_removal_impact(
    session: Session, user_id: str, org_id: str
) -> dict[str, object] | None:
    """Return counts only, never private asset content, for an org member."""
    user = session.scalar(select(User).where(User.id == user_id, User.org_id == org_id))
    if user is None:
        return None
    assets = _member_transfer_counts(session, org_id, user.id)
    blockers = _member_removal_blockers(session, org_id, user.id)
    preserved = {
        "saved_artifacts": session.query(SavedArtifact)
        .filter(SavedArtifact.org_id == org_id, SavedArtifact.created_by == user.id)
        .count()
    }
    total_assets = sum(assets.values())
    total_blockers = sum(blockers.values())
    return {
        "member_id": user.id,
        "member_email": user.email,
        "member_display_name": user.display_name,
        "assets": assets,
        "blockers": blockers,
        "preserved": preserved,
        "total_assets": total_assets,
        "total_blockers": total_blockers,
        "requires_transfer": total_assets > 0,
        "blocked": total_blockers > 0,
    }


def update_member(
    session: Session,
    user_id: str,
    org_id: str,
    *,
    role: str | None = None,
    department_id: str | None | object = UNSET,
    data_tier: str | None = None,
) -> User | None:
    if not _lock_org_for_team_mutation(session, org_id):
        return None
    user = session.scalar(select(User).where(User.id == user_id, User.org_id == org_id))
    if user is None:
        return None
    if role is not None:
        # Validate the enum. data_tier below was already checked against
        # TIER_ORDER; role was not, so any string landed straight in the column
        # and permissions_for_role then read it as "not admin" — a typo silently
        # demoted someone.
        if role not in VALID_ROLES:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown role {role!r}. Valid roles: {', '.join(VALID_ROLES)}.",
            )
        # Never leave a workspace with nobody who can administer it. Demoting the
        # last admin locks the org out of team management, integrations and data
        # sources permanently — there would be no one left able to promote anyone.
        if user.role == "admin" and role != "admin" and count_admins(session, org_id) <= 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This is the workspace's only admin. Promote another member "
                    "to admin before changing this one's role."
                ),
            )
        user.role = role
        user.permissions = permissions_for_role(role)
    if department_id is not UNSET:
        user.department_id = _validated_department_id(
            session,
            org_id,
            department_id if isinstance(department_id, str) else None,
        )
    if data_tier is not None and data_tier in TIER_ORDER:
        user.data_tier = data_tier
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="The selected department no longer exists. Refresh Team and try again.",
        ) from exc
    return user


def delete_member(
    session: Session,
    user_id: str,
    org_id: str,
    *,
    actor: str | None = None,
    transfer_to_user_id: str | None = None,
) -> bool:
    if not _lock_org_for_team_mutation(session, org_id):
        return False
    user = session.scalar(select(User).where(User.id == user_id, User.org_id == org_id))
    if user is None:
        return False
    if user.role == "admin" and count_admins(session, org_id) <= 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "This is the workspace's only admin. Promote another member to "
                "admin before removing this one."
            ),
        )
    blockers = _member_removal_blockers(session, org_id, user.id)
    total_blockers = sum(blockers.values())
    if total_blockers:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "member_removal_blocked",
                "message": (
                    "This member still has private or identity-bound records that "
                    "cannot be transferred safely. Resolve them before removal."
                ),
                "blockers": blockers,
                "total_blockers": total_blockers,
            },
        )

    assets = _member_transfer_counts(session, org_id, user.id)
    total_assets = sum(assets.values())
    if total_assets and not transfer_to_user_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "member_transfer_required",
                "message": (
                    "Select another active workspace member to receive this "
                    "member's automations, conversations, and workflows."
                ),
                "assets": assets,
                "total_assets": total_assets,
            },
        )

    transfer_target: User | None = None
    if transfer_to_user_id:
        transfer_target = session.scalar(
            select(User).where(
                User.id == transfer_to_user_id,
                User.org_id == org_id,
            )
        )
        if transfer_target is None or transfer_target.id == user.id:
            raise HTTPException(
                status_code=422,
                detail="Transfer target must be another active member of this workspace.",
            )

    transferred = {key: 0 for key in assets}
    if transfer_target is not None:
        # Ownership, pausing/revocation, principal removal, and the audit record
        # commit together. created_by_name remains the original attribution.
        transferred["automations"] = (
            session.query(Automation)
            .filter(Automation.org_id == org_id, Automation.user_id == user.id)
            .update(
                {
                    Automation.user_id: transfer_target.id,
                    Automation.enabled: False,
                    Automation.status: "paused",
                    Automation.trigger_token_hash: None,
                },
                synchronize_session=False,
            )
        )
        transferred_threads = (
            session.query(Thread)
            .filter(Thread.org_id == org_id, Thread.created_by == user.id)
            .update(
                {Thread.created_by: transfer_target.id},
                synchronize_session=False,
            )
        )
        if transferred_threads != assets["private_threads"] + assets["shared_threads"]:
            raise HTTPException(
                status_code=409,
                detail="Member assets changed during removal. Refresh Team and try again.",
            )
        transferred["private_threads"] = assets["private_threads"]
        transferred["shared_threads"] = assets["shared_threads"]
        transferred["workflow_runs"] = (
            session.query(WorkflowRun)
            .filter(WorkflowRun.org_id == org_id, WorkflowRun.created_by == user.id)
            .update(
                {WorkflowRun.created_by: transfer_target.id},
                synchronize_session=False,
            )
        )
        if transferred != assets:
            raise HTTPException(
                status_code=409,
                detail="Member assets changed during removal. Refresh Team and try again.",
            )

    detached_saved_artifacts = (
        session.query(SavedArtifact)
        .filter(SavedArtifact.org_id == org_id, SavedArtifact.created_by == user.id)
        .update(
            {SavedArtifact.created_by: None},
            synchronize_session=False,
        )
    )

    removed_notifications = (
        session.query(Notification)
        .filter(Notification.user_id == user.id)
        .delete(synchronize_session=False)
    )
    session.add(
        AuditEvent(
            org_id=org_id,
            event_type="team.member.removed",
            actor=actor,
            payload={
                "user_id": user.id,
                "transfer_to_user_id": transfer_target.id if transfer_target else None,
                "transferred_assets": transferred,
                "paused_automations": transferred["automations"],
                "removed_notifications": removed_notifications,
                "detached_saved_artifacts": detached_saved_artifacts,
            },
        )
    )
    session.delete(user)
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    return True


INVITE_TTL = timedelta(days=7)


def create_invite(
    session: Session,
    org_id: str,
    email: str,
    role: str = "member",
    department_id: str | None = None,
    data_tier: str = "normal",
) -> Invite:
    """Create (or refresh) a pending invite for an email in an org."""
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown role {role!r}. Valid roles: {', '.join(VALID_ROLES)}.",
        )
    if not _lock_org_for_team_mutation(session, org_id):
        raise HTTPException(status_code=404, detail="Workspace not found.")
    email = normalize_email(email)
    tier = data_tier if data_tier in TIER_ORDER else "normal"
    department_id = _validated_department_id(session, org_id, department_id)
    existing = session.scalar(
        select(Invite).where(
            Invite.org_id == org_id, Invite.email == email, Invite.status == "pending"
        )
    )
    if existing:
        existing.role = role
        existing.department_id = department_id
        existing.data_tier = tier
        # Reissuing an invite both refreshes its lifetime and invalidates any
        # older copied link for this org/email pair.
        existing.token = secrets.token_urlsafe(16)
        existing.created_at = now_utc()
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="The selected department no longer exists. Refresh Team and try again.",
            ) from exc
        return existing
    invite = Invite(
        org_id=org_id,
        email=email,
        role=role,
        department_id=department_id,
        data_tier=tier,
        token=secrets.token_urlsafe(16),
    )
    session.add(invite)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="The selected department no longer exists. Refresh Team and try again.",
        ) from exc
    return invite


def list_invites(session: Session, org_id: str, status: str = "pending") -> list[Invite]:
    return (
        session.query(Invite)
        .filter(Invite.org_id == org_id, Invite.status == status)
        .order_by(desc(Invite.created_at))
        .all()
    )


def revoke_invite(session: Session, org_id: str, invite_id: str) -> bool:
    claimed = session.execute(
        update(Invite)
        .where(
            Invite.id == invite_id,
            Invite.org_id == org_id,
            Invite.status == "pending",
        )
        .values(status="revoked")
    )
    if claimed.rowcount != 1:
        session.rollback()
        return False
    session.commit()
    return True


def accept_invite_by_token(
    session: Session,
    token: str,
    email: str,
    display_name: str,
) -> User | None:
    """Atomically consume one fresh invite matching this exact token and email."""
    if not token or len(token) > 256:
        return None
    email_norm = normalize_email(email)
    cutoff = (now_utc() - INVITE_TTL).replace(tzinfo=None)
    invite = (
        session.execute(
            update(Invite)
            .where(
                Invite.token == token,
                Invite.email == email_norm,
                Invite.status == "pending",
                Invite.created_at >= cutoff,
            )
            .values(status="accepted")
            .execution_options(synchronize_session="fetch")
            .returning(
                Invite.org_id,
                Invite.role,
                Invite.department_id,
                Invite.data_tier,
            )
        )
        .mappings()
        .one_or_none()
    )
    if invite is None:
        session.rollback()
        return None
    user = User(
        org_id=invite["org_id"],
        email=email_norm,
        display_name=display_name,
        role=invite["role"],
        department_id=invite["department_id"],
        permissions=permissions_for_role(invite["role"]),
        data_tier=invite["data_tier"] or "normal",
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        # A concurrent acceptance may have created this globally unique email.
        # Roll back the status update too, never leaving an accepted invite with
        # no user in its target workspace.
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="An account already exists for this email.",
        ) from exc
    return user


# --- Automations (NL scheduled tasks) --------------------------------------

# Trigger keys are retained for seven days. Reusing a key after expiry is a new
# request; at most 100 expired rows are removed by each accepted trigger so
# cleanup work stays bounded without a separate scheduler.
AUTOMATION_TRIGGER_RETENTION = timedelta(days=7)
AUTOMATION_TRIGGER_CLEANUP_LIMIT = 100


def cleanup_automation_trigger_requests(
    session: Session,
    *,
    now: datetime | None = None,
) -> int:
    cutoff = (now or now_utc()) - AUTOMATION_TRIGGER_RETENTION
    expired_ids = session.scalars(
        select(AutomationTriggerRequest.id)
        .where(AutomationTriggerRequest.created_at < cutoff)
        .order_by(AutomationTriggerRequest.created_at)
        .limit(AUTOMATION_TRIGGER_CLEANUP_LIMIT)
    ).all()
    if not expired_ids:
        return 0
    deleted = (
        session.query(AutomationTriggerRequest)
        .filter(AutomationTriggerRequest.id.in_(expired_ids))
        .delete(synchronize_session=False)
    )
    session.commit()
    return deleted


def reserve_automation_trigger(
    session: Session,
    *,
    automation_id: str,
    org_id: str,
    idempotency_key: str,
    request_hash: str,
) -> tuple[str, AutomationTriggerRequest]:
    """Reserve one trigger, resolving concurrent unique-key races durably."""
    cleanup_automation_trigger_requests(session)

    def _existing() -> AutomationTriggerRequest | None:
        return session.scalar(
            select(AutomationTriggerRequest).where(
                AutomationTriggerRequest.automation_id == automation_id,
                AutomationTriggerRequest.idempotency_key == idempotency_key,
            )
        )

    existing = _existing()
    if existing is not None:
        return ("conflict" if existing.request_hash != request_hash else "replay", existing)

    request = AutomationTriggerRequest(
        automation_id=automation_id,
        org_id=org_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        status="running",
    )
    session.add(request)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = _existing()
        if existing is None:
            raise
        return ("conflict" if existing.request_hash != request_hash else "replay", existing)
    return "reserved", request


def finish_automation_trigger(
    session: Session,
    *,
    request_id: str,
    status: str,
    response: dict,
    http_status: int,
) -> bool:
    if status not in {"completed", "outcome_unknown"}:
        raise ValueError(f"Unsupported automation trigger status: {status}")
    updated = (
        session.query(AutomationTriggerRequest)
        .filter(
            AutomationTriggerRequest.id == request_id,
            AutomationTriggerRequest.status == "running",
        )
        .update(
            {
                "status": status,
                "response": response,
                "http_status": http_status,
                "updated_at": now_utc(),
            },
            synchronize_session=False,
        )
    )
    session.commit()
    return updated == 1


def create_automation(
    session: Session,
    *,
    org_id: str,
    user_id: str | None,
    name: str,
    prompt: str,
    cadence: str,
    status: str = "active",
    deliver_to: dict | None = None,
) -> Automation:
    auto = Automation(
        org_id=org_id,
        user_id=user_id,
        name=name,
        prompt=prompt,
        cadence=cadence,
        status=status,
        deliver_to=deliver_to,
    )
    session.add(auto)
    session.commit()
    return auto


def update_automation(
    session: Session,
    org_id: str,
    automation_id: str,
    *,
    name: str | None = None,
    prompt: str | None = None,
    cadence: str | None = None,
    enabled: bool | None = None,
    status: str | None = None,
    deliver_to: object = UNSET,
) -> Automation | None:
    auto = session.get(Automation, automation_id)
    if auto is None or auto.org_id != org_id:
        return None
    if name is not None:
        auto.name = name
    if prompt is not None:
        auto.prompt = prompt
    if cadence is not None:
        auto.cadence = cadence
    if enabled is not None:
        auto.enabled = enabled
    if status is not None:
        auto.status = status
    if deliver_to is not UNSET:
        auto.deliver_to = deliver_to  # type: ignore[assignment]
    session.commit()
    return auto


def list_automations(session: Session, org_id: str) -> list[Automation]:
    return (
        session.query(Automation)
        .filter(Automation.org_id == org_id)
        .order_by(desc(Automation.created_at))
        .all()
    )


# How often each cadence is due. `manual` is intentionally absent — those only
# run via POST /automations/{id}/run.
CADENCE_INTERVALS = {
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
}


def list_due_automations(session: Session, now: datetime | None = None) -> list[Automation]:
    """Active scheduled automations (across all orgs) whose cadence interval has
    elapsed since their last run. Never-run automations are due immediately.
    Consumed by the Celery beat scheduler."""
    now = now or now_utc()
    # Compare in aware-UTC throughout: now_utc() is aware, but last_run_at comes
    # from a tz-naive column, and a caller may pass a naive `now`. Normalize both
    # so the comparison never raises "can't compare naive and aware datetimes".
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    candidates = (
        session.query(Automation)
        .filter(
            Automation.enabled.is_(True),
            Automation.status == "active",
            Automation.cadence.in_(tuple(CADENCE_INTERVALS)),
        )
        .all()
    )
    due = []
    for a in candidates:
        if a.last_run_at is None:
            due.append(a)
            continue
        # last_run_at is stored in a tz-naive DateTime column (Postgres drops the
        # tzinfo), so coerce to aware-UTC before comparing with the aware `now` —
        # otherwise the comparison raises TypeError and fails the whole tick.
        last = a.last_run_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if last <= now - CADENCE_INTERVALS[a.cadence]:
            due.append(a)
    return due


def delete_automation(session: Session, org_id: str, automation_id: str) -> bool:
    n = (
        session.query(Automation)
        .filter(Automation.id == automation_id, Automation.org_id == org_id)
        .delete()
    )
    session.commit()
    return bool(n)


def record_automation_run(
    session: Session,
    automation_id: str,
    result: str,
    connectors: list[str] | None = None,
    delivery: dict | None = None,
) -> None:
    auto = session.get(Automation, automation_id)
    if auto:
        auto.last_run_at = now_utc()
        auto.last_result = result
        if connectors is not None:
            auto.last_connectors = connectors
        if delivery is not None:
            auto.last_delivery = delivery
        session.commit()


def list_documents_since(
    session: Session,
    org_id: str,
    since: datetime | None,
    *,
    requester_permissions: list[str],
    requester_tier: str,
    limit: int = 50,
) -> list[tuple[str, str, datetime, str]]:
    """(source_type, title, ingested_at) for documents ingested after `since` —
    the 'what's new' feed an automation run summarizes."""
    from memory.retriever import _tier_visible, _visible

    q = session.query(SourceDocumentRecord).filter(SourceDocumentRecord.org_id == org_id)
    if since is not None:
        q = q.filter(SourceDocumentRecord.ingested_at > since)
    visible: list[tuple[str, str, datetime, str]] = []
    batch_size = min(max(limit, 25), 100)
    for record in q.order_by(desc(SourceDocumentRecord.ingested_at)).yield_per(batch_size):
        if not _visible(record.permissions, requester_permissions):
            continue
        if not _tier_visible(record.data_tier, requester_tier):
            continue
        visible.append(
            (record.source_type, record.title, record.ingested_at, record.data_tier or "normal")
        )
        if len(visible) >= limit:
            break
    return visible
