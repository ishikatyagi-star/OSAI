"""saved artifacts — pinned answer outputs that outlive their conversation

Revision ID: 20260712_0018
Revises: 20260712_0017
Create Date: 2026-07-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260712_0018"
down_revision: str | Sequence[str] | None = "20260712_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_artifacts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("orgs.id"), nullable=False, index=True),
        sa.Column("thread_id", sa.String(), nullable=True, index=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="answer_summary"),
        sa.Column("data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_by_name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("saved_artifacts")
