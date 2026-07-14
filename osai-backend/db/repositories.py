import logging
import secrets
from collections.abc import Sequence
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.schemas.connector import SourceDocument
from db.models import (
    ActionItemRecord,
    AuditEvent,
    Automation,
    Chunk,
    ConnectorAccount,
    ConnectorAction,
    ConnectorRecord,
    Department,
    Invite,
    Org,
    OrgMemory,
    SourceDocumentRecord,
    SyncRun,
    User,
    WorkflowRun,
    now_utc,
)
from db.session import SessionLocal
from memory.chunker import chunk_document

logger = logging.getLogger("osai.repositories")


def seed_demo_data(session: Session, org_id: str = "demo-org") -> None:
    if session.get(Org, org_id) is None:
        session.add(Org(id=org_id, name="OSAI Demo Org"))
        session.flush()
    if session.scalar(select(User).where(User.email == "admin@osai.local")) is None:
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
        is_security = any(
            kw in (d["title"] or "").lower() for kw in ("security", "vpc", "ollama")
        )
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
                            "Anish: I will write the Zoom "
                            "webhook endpoint by next Tuesday."
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
                            "Ishika: I will prepare the UI "
                            "mockups for settings panel by Friday."
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
                "created_at": (
                    datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=18)
                ),
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
                            datetime.datetime.now(datetime.UTC)
                            - datetime.timedelta(hours=12)
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
                "started_at": (
                    datetime.datetime.now(datetime.UTC)
                    - datetime.timedelta(hours=4)
                ),
                "finished_at": (
                    datetime.datetime.now(datetime.UTC)
                    - datetime.timedelta(hours=3, minutes=55)
                ),
            },
            {
                "connector_key": "slack",
                "status": "succeeded",
                "documents_seen": 45,
                "documents_indexed": 45,
                "error": None,
                "started_at": (
                    datetime.datetime.now(datetime.UTC)
                    - datetime.timedelta(hours=1)
                ),
                "finished_at": (
                    datetime.datetime.now(datetime.UTC)
                    - datetime.timedelta(hours=1)
                ),
            },
            {
                "connector_key": "freshdesk",
                "status": "failed",
                "documents_seen": 0,
                "documents_indexed": 0,
                "error": "Invalid API credentials provided",
                "started_at": (
                    datetime.datetime.now(datetime.UTC)
                    - datetime.timedelta(days=1)
                ),
                "finished_at": (
                    datetime.datetime.now(datetime.UTC)
                    - datetime.timedelta(days=1)
                ),
            },
            {
                "connector_key": "google_drive",
                "status": "succeeded",
                "documents_seen": 8,
                "documents_indexed": 8,
                "error": None,
                "started_at": (
                    datetime.datetime.now(datetime.UTC)
                    - datetime.timedelta(hours=8)
                ),
                "finished_at": (
                    datetime.datetime.now(datetime.UTC)
                    - datetime.timedelta(hours=7, minutes=52)
                ),
            },
            {
                "connector_key": "slack",
                "status": "succeeded",
                "documents_seen": 112,
                "documents_indexed": 110,
                "error": None,
                "started_at": (
                    datetime.datetime.now(datetime.UTC)
                    - datetime.timedelta(minutes=30)
                ),
                "finished_at": (
                    datetime.datetime.now(datetime.UTC)
                    - datetime.timedelta(minutes=28)
                ),
            },
            {
                "connector_key": "notion",
                "status": "succeeded",
                "documents_seen": 5,
                "documents_indexed": 5,
                "error": None,
                "started_at": (
                    datetime.datetime.now(datetime.UTC)
                    - datetime.timedelta(minutes=15)
                ),
                "finished_at": (
                    datetime.datetime.now(datetime.UTC)
                    - datetime.timedelta(minutes=14)
                ),
            },
            {
                "connector_key": "freshdesk",
                "status": "succeeded",
                "documents_seen": 12,
                "documents_indexed": 12,
                "error": None,
                "started_at": (
                    datetime.datetime.now(datetime.UTC)
                    - datetime.timedelta(minutes=5)
                ),
                "finished_at": (
                    datetime.datetime.now(datetime.UTC)
                    - datetime.timedelta(minutes=4)
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
                account.last_sync_at.isoformat() if account and account.last_sync_at else None
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
        raise HTTPException(
            status_code=401, detail="Session is no longer valid; sign in again."
        )
    return user


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


# Proposed agent actions are persisted so a "confirm" can succeed even if a
# different web worker (or the same process after a restart/cold-start) handles
# it — an in-process dict alone loses them. Stored in connector_actions with
# status="proposed"; the full execution descriptor lives in the payload.
_PROPOSED_TTL_HOURS = 24


def save_proposed_action(action_id: str, descriptor: dict) -> None:
    with SessionLocal() as session:
        if session.get(ConnectorAction, action_id) is not None:
            return
        session.add(
            ConnectorAction(
                id=action_id,
                org_id=descriptor.get("org_id", ""),
                connector_key=descriptor.get("tool", "unknown"),
                action_type=descriptor.get("action", ""),
                status="proposed",
                payload=descriptor,
            )
        )
        session.commit()


def load_proposed_action(action_id: str) -> dict | None:
    try:
        with SessionLocal() as session:
            row = session.get(ConnectorAction, action_id)
            if row is None or row.status != "proposed":
                return None
            if row.created_at and now_utc() - row.created_at > timedelta(
                hours=_PROPOSED_TTL_HOURS
            ):
                return None
            return dict(row.payload or {})
    except SQLAlchemyError:
        return None


def claim_proposed_action(action_id: str) -> str:
    """Atomically claim a proposed action so exactly one confirm can execute it.

    Returns "claimed" (this caller won the race and may execute), "taken" (a
    concurrent or prior confirm already consumed it), or "absent" (no durable
    row — in-process-only context such as unit tests, where cross-worker races
    don't apply).

    The single `UPDATE ... WHERE status='proposed'` is the guard: under READ
    COMMITTED two concurrent confirms serialize on the row, so the loser matches
    zero rows. This prevents double-executed connector side effects — duplicate
    tickets, pages, or messages (SEC-007)."""
    try:
        with SessionLocal() as session:
            if session.get(ConnectorAction, action_id) is None:
                return "absent"
            updated = (
                session.query(ConnectorAction)
                .filter(
                    ConnectorAction.id == action_id,
                    ConnectorAction.status == "proposed",
                )
                .update({"status": "consumed"}, synchronize_session=False)
            )
            session.commit()
            return "claimed" if updated == 1 else "taken"
    except SQLAlchemyError:
        # DB unavailable: we lose the durable guard rather than hard-block a
        # legitimate confirm. The in-process fast-path dict still prevents the
        # common same-worker double-click.
        return "absent"


def discard_proposed_action(action_id: str) -> None:
    with SessionLocal() as session:
        row = session.get(ConnectorAction, action_id)
        if row is not None:
            row.status = "consumed"
            session.commit()


def ensure_connector_account(
    session: Session, org_id: str, connector_key: str
) -> ConnectorAccount:
    """Get (or create) the ConnectorAccount row for an org+connector. A Composio
    OAuth connection may not have created one, but we need it to persist the
    connected-account identity used for reconnect handling."""
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
    session.query(Chunk).filter(
        Chunk.org_id == org_id, Chunk.source_type == source_type
    ).delete(synchronize_session=False)
    session.query(SourceDocumentRecord).filter(
        SourceDocumentRecord.id.in_(doc_ids)
    ).delete(synchronize_session=False)
    session.flush()
    return len(doc_ids)


def list_sync_runs(session: Session, org_id: str, limit: int = 50) -> Sequence[SyncRun]:
    return session.scalars(
        select(SyncRun)
        .where(SyncRun.org_id == org_id)
        .order_by(desc(SyncRun.started_at))
        .limit(limit)
    ).all()


def list_workflow_runs(session: Session, org_id: str, limit: int = 50) -> Sequence[WorkflowRun]:
    return session.scalars(
        select(WorkflowRun)
        .where(WorkflowRun.org_id == org_id)
        .order_by(desc(WorkflowRun.created_at))
        .limit(limit)
    ).all()


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
            actor="system",
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
        select(ActionItemRecord).where(ActionItemRecord.workflow_run_id == run_id)
    ).all()
    return {
        "id": run.id,
        "org_id": run.org_id,
        "kind": run.kind,
        "status": run.status,
        "input_text": run.input_text,
        "destination": run.destination,
        "data_tier": run.data_tier,
        "model_route": run.model_route,
        "created_at": run.created_at.isoformat(),
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
                "executed_at": item.executed_at.isoformat() if item.executed_at else None,
            }
            for item in items
        ],
    }


def approve_action_item(
    session: Session,
    *,
    item_id: str,
    org_id: str,
) -> ActionItemRecord | None:
    """Mark an action item as approved and record a ConnectorAction."""
    item = session.get(ActionItemRecord, item_id)
    if item is None:
        return None
    if item.status not in ("needs_review", "failed"):
        return item  # idempotent — already approved/executed
    item.status = "approved"
    session.add(
        ConnectorAction(
            org_id=org_id,
            connector_key=item.destination if item.destination != "manual" else "notion",
            action_type="execute_action_item",
            status="pending",
            payload={"action_item_id": item_id, "title": item.title},
        )
    )
    session.add(
        AuditEvent(
            org_id=org_id,
            event_type="action_item.approved",
            actor="user",
            payload={"item_id": item_id, "destination": item.destination},
        )
    )
    session.commit()
    return item


def update_action_item_execution(
    session: Session,
    *,
    item_id: str,
    status: str,
    external_url: str | None = None,
) -> None:
    """Record the outcome of executing an action item."""
    from db.models import now_utc

    item = session.get(ActionItemRecord, item_id)
    if item is None:
        return
    item.status = status
    item.external_url = external_url
    item.executed_at = now_utc()
    session.add(
        AuditEvent(
            org_id="",
            event_type=f"action_item.{status}",
            actor="system",
            payload={"item_id": item_id, "external_url": external_url},
        )
    )
    session.commit()


def provision_org(
    session: Session,
    *,
    name: str,
    admin_email: str,
    admin_name: str,
) -> tuple[Org, User]:
    """Provision a new organization, its admin user, and seed connector accounts."""
    # Check duplicate user email
    existing_user = session.scalar(select(User).where(User.email == admin_email))
    if existing_user is not None:
        raise ValueError(f"User with email {admin_email!r} already exists")

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

    # Seed default Connector accounts
    for key in ("notion", "slack", "freshdesk", "google_drive"):
        session.add(
            ConnectorAccount(
                org_id=org.id,
                connector_key=key,
                auth_state="not_configured",
            )
        )

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
        r[0]
        for r in session.query(WorkflowRun.id).filter(WorkflowRun.org_id == org_id).all()
    ]
    counts = {
        "chunks": session.query(Chunk).filter(Chunk.org_id == org_id).delete(),
        "documents": session.query(SourceDocumentRecord)
        .filter(SourceDocumentRecord.org_id == org_id)
        .delete(),
        "action_items": (
            session.query(ActionItemRecord)
            .filter(ActionItemRecord.workflow_run_id.in_(run_ids))
            .delete(synchronize_session=False)
            if run_ids
            else 0
        ),
        "workflow_runs": session.query(WorkflowRun)
        .filter(WorkflowRun.org_id == org_id)
        .delete(),
        "org_memory": session.query(OrgMemory).filter(OrgMemory.org_id == org_id).delete(),
        "sync_runs": session.query(SyncRun).filter(SyncRun.org_id == org_id).delete(),
    }
    session.commit()
    return counts


# --- Team: departments, invites, members -----------------------------------

def permissions_for_role(role: str) -> list[str]:
    """Map a role to data-access grants used by permission-aware retrieval."""
    if role == "admin":
        return ["org:admin", "source:all"]
    return ["source:all"]


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


def list_members(session: Session, org_id: str) -> list[User]:
    return (
        session.query(User)
        .filter(User.org_id == org_id)
        .order_by(User.created_at)
        .all()
    )


def update_member(
    session: Session,
    user_id: str,
    org_id: str,
    *,
    role: str | None = None,
    department_id: str | None = None,
    data_tier: str | None = None,
) -> User | None:
    user = session.scalar(
        select(User).where(User.id == user_id, User.org_id == org_id)
    )
    if user is None:
        return None
    if role is not None:
        user.role = role
        user.permissions = permissions_for_role(role)
    if department_id is not None:
        user.department_id = department_id or None
    if data_tier is not None and data_tier in TIER_ORDER:
        user.data_tier = data_tier
    session.commit()
    return user


def create_invite(
    session: Session,
    org_id: str,
    email: str,
    role: str = "member",
    department_id: str | None = None,
    data_tier: str = "normal",
) -> Invite:
    """Create (or refresh) a pending invite for an email in an org."""
    email = email.strip().lower()
    tier = data_tier if data_tier in TIER_ORDER else "normal"
    existing = session.scalar(
        select(Invite).where(
            Invite.org_id == org_id, Invite.email == email, Invite.status == "pending"
        )
    )
    if existing:
        existing.role = role
        existing.department_id = department_id
        existing.data_tier = tier
        session.commit()
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
    session.commit()
    return invite


def list_invites(session: Session, org_id: str, status: str = "pending") -> list[Invite]:
    return (
        session.query(Invite)
        .filter(Invite.org_id == org_id, Invite.status == status)
        .order_by(desc(Invite.created_at))
        .all()
    )


def accept_invite_for_email(session: Session, email: str, display_name: str) -> User | None:
    """If a pending invite exists for this verified email, create the user in that
    org with the invited role/department and mark the invite accepted. Returns the
    new user, or None if there's no invite (caller then provisions a new org)."""
    email_norm = email.strip().lower()
    invite = session.scalar(
        select(Invite).where(Invite.email == email_norm, Invite.status == "pending")
    )
    if invite is None:
        return None
    user = User(
        org_id=invite.org_id,
        email=email,
        display_name=display_name,
        role=invite.role,
        department_id=invite.department_id,
        permissions=permissions_for_role(invite.role),
        data_tier=invite.data_tier or "normal",
    )
    session.add(user)
    invite.status = "accepted"
    session.commit()
    return user


# --- Automations (NL scheduled tasks) --------------------------------------

# Sentinel distinguishing "field not sent" from an explicit None/clear on update.
UNSET: object = object()


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
        org_id=org_id, user_id=user_id, name=name, prompt=prompt, cadence=cadence,
        status=status, deliver_to=deliver_to,
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
    candidates = (
        session.query(Automation)
        .filter(
            Automation.enabled.is_(True),
            Automation.status == "active",
            Automation.cadence.in_(tuple(CADENCE_INTERVALS)),
        )
        .all()
    )
    return [
        a
        for a in candidates
        if a.last_run_at is None or a.last_run_at <= now - CADENCE_INTERVALS[a.cadence]
    ]


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
    session: Session, org_id: str, since: datetime | None, limit: int = 50
) -> list[tuple[str, str, datetime]]:
    """(source_type, title, ingested_at) for documents ingested after `since` —
    the 'what's new' feed an automation run summarizes."""
    q = session.query(
        SourceDocumentRecord.source_type,
        SourceDocumentRecord.title,
        SourceDocumentRecord.ingested_at,
    ).filter(SourceDocumentRecord.org_id == org_id)
    if since is not None:
        q = q.filter(SourceDocumentRecord.ingested_at > since)
    return [tuple(r) for r in q.order_by(desc(SourceDocumentRecord.ingested_at)).limit(limit)]
