"""Persist single-use Slack request markers.

Revision ID: 20260722_0028
Revises: 20260721_0027
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0028"
down_revision: str | Sequence[str] | None = "20260721_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "slack_request_uses",
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("request_hash"),
    )
    op.create_index(
        op.f("ix_slack_request_uses_expires_at"),
        "slack_request_uses",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_slack_request_uses_expires_at"), table_name="slack_request_uses")
    op.drop_table("slack_request_uses")
