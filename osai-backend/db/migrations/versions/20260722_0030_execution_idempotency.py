"""Durable workflow execution and automation trigger idempotency.

Revision ID: 20260722_0030
Revises: 20260722_0029
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0030"
down_revision: str | Sequence[str] | None = "20260722_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "action_items",
        sa.Column("execution_key", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "action_items",
        sa.Column("execution_started_at", sa.DateTime(), nullable=True),
    )
    # Older `failed` executions may have committed at a provider before a
    # timeout. Existing in-flight rows are equally ambiguous after deployment.
    op.execute(
        sa.text(
            "UPDATE action_items SET status = 'outcome_unknown' "
            "WHERE status IN ('failed', 'executing')"
        )
    )

    op.create_table(
        "automation_trigger_requests",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("automation_id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("response", sa.JSON(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "automation_id",
            "idempotency_key",
            name="uq_automation_trigger_request_key",
        ),
    )
    op.create_index(
        op.f("ix_automation_trigger_requests_automation_id"),
        "automation_trigger_requests",
        ["automation_id"],
    )
    op.create_index(
        op.f("ix_automation_trigger_requests_org_id"),
        "automation_trigger_requests",
        ["org_id"],
    )
    op.create_index(
        op.f("ix_automation_trigger_requests_status"),
        "automation_trigger_requests",
        ["status"],
    )
    op.create_index(
        op.f("ix_automation_trigger_requests_created_at"),
        "automation_trigger_requests",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_automation_trigger_requests_created_at"),
        table_name="automation_trigger_requests",
    )
    op.drop_index(
        op.f("ix_automation_trigger_requests_status"),
        table_name="automation_trigger_requests",
    )
    op.drop_index(
        op.f("ix_automation_trigger_requests_org_id"),
        table_name="automation_trigger_requests",
    )
    op.drop_index(
        op.f("ix_automation_trigger_requests_automation_id"),
        table_name="automation_trigger_requests",
    )
    op.drop_table("automation_trigger_requests")
    op.execute(
        sa.text(
            "UPDATE action_items SET status = 'failed' "
            "WHERE status IN ('failed_preflight', 'outcome_unknown')"
        )
    )
    op.drop_column("action_items", "execution_started_at")
    op.drop_column("action_items", "execution_key")
