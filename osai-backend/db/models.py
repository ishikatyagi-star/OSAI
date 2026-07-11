from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def new_id() -> str:
    return str(uuid4())


def now_utc() -> datetime:
    return datetime.now(UTC)


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String, nullable=False)
    data_routing: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String, ForeignKey("orgs.id"), index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="admin")
    department_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Data-clearance tier (normal|amber|red): the highest data sensitivity this
    # member may see. Admins see everything regardless of this.
    data_tier: Mapped[str] = mapped_column(String, default="normal")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String, ForeignKey("orgs.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    color: Mapped[str] = mapped_column(String, default="#6a4cf5")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class Invite(Base):
    """A pending team invitation. Auto-accepted on first sign-in by matching the
    verified email — so an admin can add teammates with a role/department before
    they ever log in, and they land in the same org."""

    __tablename__ = "invites"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String, ForeignKey("orgs.id"), index=True)
    email: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String, default="member")
    department_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Clearance tier the invited member will get on accept.
    data_tier: Mapped[str] = mapped_column(String, default="normal")
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    token: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class ConnectorRecord(Base):
    __tablename__ = "connectors"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class ConnectorAccount(Base):
    __tablename__ = "connector_accounts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String, ForeignKey("orgs.id"), index=True)
    connector_key: Mapped[str] = mapped_column(String, ForeignKey("connectors.key"), index=True)
    auth_state: Mapped[str] = mapped_column(String, default="not_configured")
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    # Per-info sensitivity overrides: list of {"pattern": str, "tier": str}. On
    # ingest, a document whose path/url/title contains `pattern` inherits `tier`
    # (most-specific match wins) instead of the connector's flat default.
    tier_rules: Mapped[list[dict]] = mapped_column(JSON, default=list)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String, ForeignKey("orgs.id"), index=True)
    connector_key: Mapped[str] = mapped_column(String, ForeignKey("connectors.key"), index=True)
    status: Mapped[str] = mapped_column(String, index=True)
    cursor: Mapped[str | None] = mapped_column(String, nullable=True)
    documents_seen: Mapped[int] = mapped_column(Integer, default=0)
    documents_indexed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SourceDocumentRecord(Base):
    __tablename__ = "source_documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(String, index=True)
    source_type: Mapped[str] = mapped_column(String, index=True)
    external_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    data_tier: Mapped[str] = mapped_column(String, default="normal")
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_document_id: Mapped[str] = mapped_column(
        String, ForeignKey("source_documents.id"), index=True
    )
    org_id: Mapped[str] = mapped_column(String, index=True)
    source_type: Mapped[str] = mapped_column(String, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    content_preview: Mapped[str] = mapped_column(Text)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    data_tier: Mapped[str] = mapped_column(String, default="normal")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String, ForeignKey("orgs.id"), index=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, index=True)
    input_text: Mapped[str] = mapped_column(Text)
    destination: Mapped[str] = mapped_column(String, default="manual")
    data_tier: Mapped[str] = mapped_column(String, default="normal")
    model_route: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)


class ActionItemRecord(Base):
    __tablename__ = "action_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    workflow_run_id: Mapped[str] = mapped_column(String, ForeignKey("workflow_runs.id"), index=True)
    title: Mapped[str] = mapped_column(String)
    owner: Mapped[str | None] = mapped_column(String, nullable=True)
    due_date: Mapped[str | None] = mapped_column(String, nullable=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    destination: Mapped[str] = mapped_column(String, default="manual")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String, default="needs_review")
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class ConnectorAction(Base):
    __tablename__ = "connector_actions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String, ForeignKey("orgs.id"), index=True)
    connector_key: Mapped[str] = mapped_column(String, ForeignKey("connectors.key"), index=True)
    action_type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class Automation(Base):
    """A natural-language task that runs unattended on a cadence (or on demand):
    OSAI runs the agent with `prompt` for the org and stores the result. The
    executor is a seam — today it calls the in-house agent; later it can call a
    Hermes sidecar instead."""

    __tablename__ = "automations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String, ForeignKey("orgs.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String)
    prompt: Mapped[str] = mapped_column(Text)
    cadence: Mapped[str] = mapped_column(String, default="manual")  # manual|hourly|daily|weekly
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # draft = agent still clarifying; active = runs on cadence; paused = kept, not scheduled.
    status: Mapped[str] = mapped_column(String, default="active")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Connector snapshot at last run, so the next run can report newly added sources.
    last_connectors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Where run results are delivered, e.g. {"channel": "slack", "target": "#general"}.
    # None = results only land in last_result (the dashboard).
    deliver_to: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Outcome of the most recent delivery attempt (status + error), for honest UI.
    last_delivery: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    actor: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)


class ModelCall(Base):
    __tablename__ = "model_calls"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String, ForeignKey("orgs.id"), index=True)
    provider: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    prompt_version: Mapped[str] = mapped_column(String)
    schema_version: Mapped[str] = mapped_column(String)
    data_tier: Mapped[str] = mapped_column(String, default="normal")
    trace_id: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class AnswerFeedback(Base):
    """User verdicts on Ask answers, stored with the retrieval trace.

    This is the eval dataset for retrieval-quality work: each row captures what
    was asked, what was answered, which sources were cited (with scores/tiers),
    which model route produced it, and what the user thought of it."""

    __tablename__ = "answer_feedback"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String, ForeignKey("orgs.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    query: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    rating: Mapped[str] = mapped_column(String, index=True)  # up | down
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Titles the user flagged as irrelevant/wrong sources.
    wrong_sources: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Snapshot of the answer's provenance: citations (title/tool/score/tier),
    # via (osai|hermes), model_route — enough to replay the retrieval offline.
    retrieval_trace: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)


class OrgMemory(Base):
    """Evolving agent/org state — distinct from the document knowledge base.

    Holds facts, decisions, resolutions, and playbooks that OSAI accumulates and
    reuses (per Needle's "vector DBs aren't memory"): the knowledge base answers
    "what do the docs say", org_memory answers "what do we know / how do we
    usually handle this".
    """

    __tablename__ = "org_memory"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # fact | preference | decision | resolution | playbook
    kind: Mapped[str] = mapped_column(String, index=True)
    content: Mapped[str] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
