"""org decision log table

Backs the Decisions page with real persistence (it previously lived only in
local React state and vanished on reload).

Revision ID: 20260711_0013
Revises: 20260711_0012
Create Date: 2026-07-11
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260711_0013"
down_revision: str | Sequence[str] | None = "20260711_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("orgs.id"), nullable=False, index=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="proposed"),
        sa.Column("impact", sa.String(), nullable=False, server_default="medium"),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="Manual"),
        sa.Column("identified_by", sa.String(), nullable=False, server_default="source"),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("decisions")
