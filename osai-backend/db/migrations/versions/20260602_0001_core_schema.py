"""core schema

Revision ID: 20260602_0001
Revises:
Create Date: 2026-06-02
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260602_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "orgs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("data_routing", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "connectors",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "connector_accounts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("connector_key", sa.String(), sa.ForeignKey("connectors.key"), nullable=False),
        sa.Column("auth_state", sa.String(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_connector_accounts_org_id", "connector_accounts", ["org_id"])
    op.create_index(
        "ix_connector_accounts_connector_key", "connector_accounts", ["connector_key"]
    )

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("connector_key", sa.String(), sa.ForeignKey("connectors.key"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("cursor", sa.String(), nullable=True),
        sa.Column("documents_seen", sa.Integer(), nullable=False),
        sa.Column("documents_indexed", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_sync_runs_org_id", "sync_runs", ["org_id"])
    op.create_index("ix_sync_runs_connector_key", "sync_runs", ["connector_key"])
    op.create_index("ix_sync_runs_status", "sync_runs", ["status"])

    op.create_table(
        "source_documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("data_tier", sa.String(), nullable=False),
        sa.Column("source_created_at", sa.DateTime(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_source_documents_org_id", "source_documents", ["org_id"])
    op.create_index("ix_source_documents_source_type", "source_documents", ["source_type"])
    op.create_index("ix_source_documents_external_id", "source_documents", ["external_id"])
    op.create_index(
        "ix_source_documents_org_source_updated",
        "source_documents",
        ["org_id", "source_type", "source_updated_at"],
    )

    op.create_table(
        "chunks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "source_document_id",
            sa.String(),
            sa.ForeignKey("source_documents.id"),
            nullable=False,
        ),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_preview", sa.Text(), nullable=False),
        sa.Column("qdrant_point_id", sa.String(), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("data_tier", sa.String(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chunks_source_document_id", "chunks", ["source_document_id"])
    op.create_index("ix_chunks_org_id", "chunks", ["org_id"])
    op.create_index("ix_chunks_source_type", "chunks", ["source_type"])
    op.create_index(
        "ix_chunks_org_source_document",
        "chunks",
        ["org_id", "source_type", "source_document_id"],
    )

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("destination", sa.String(), nullable=False),
        sa.Column("data_tier", sa.String(), nullable=False),
        sa.Column("model_route", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_workflow_runs_org_id", "workflow_runs", ["org_id"])
    op.create_index("ix_workflow_runs_kind", "workflow_runs", ["kind"])
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])
    op.create_index("ix_workflow_runs_created_at", "workflow_runs", ["created_at"])
    op.create_index("ix_workflow_runs_org_created", "workflow_runs", ["org_id", "created_at"])

    op.create_table(
        "action_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "workflow_run_id",
            sa.String(),
            sa.ForeignKey("workflow_runs.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("destination", sa.String(), nullable=False),
        sa.Column("source_quote", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_action_items_workflow_run_id", "action_items", ["workflow_run_id"])

    op.create_table(
        "connector_actions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("connector_key", sa.String(), sa.ForeignKey("connectors.key"), nullable=False),
        sa.Column("workflow_run_id", sa.String(), sa.ForeignKey("workflow_runs.id"), nullable=True),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_connector_actions_org_id", "connector_actions", ["org_id"])
    op.create_index("ix_connector_actions_connector_key", "connector_actions", ["connector_key"])
    op.create_index(
        "ix_connector_actions_workflow_run_id",
        "connector_actions",
        ["workflow_run_id"],
    )
    op.create_index("ix_connector_actions_status", "connector_actions", ["status"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audit_events_org_id", "audit_events", ["org_id"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])
    op.create_index(
        "ix_audit_events_org_created_type",
        "audit_events",
        ["org_id", "created_at", "event_type"],
    )

    op.create_table(
        "model_calls",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("workflow_run_id", sa.String(), sa.ForeignKey("workflow_runs.id"), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("data_tier", sa.String(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_model_calls_org_id", "model_calls", ["org_id"])
    op.create_index("ix_model_calls_workflow_run_id", "model_calls", ["workflow_run_id"])
    op.create_index("ix_model_calls_trace_id", "model_calls", ["trace_id"])


def downgrade() -> None:
    op.drop_table("model_calls")
    op.drop_table("audit_events")
    op.drop_table("connector_actions")
    op.drop_table("action_items")
    op.drop_table("workflow_runs")
    op.drop_table("chunks")
    op.drop_table("source_documents")
    op.drop_table("sync_runs")
    op.drop_table("connector_accounts")
    op.drop_table("users")
    op.drop_table("connectors")
    op.drop_table("orgs")
