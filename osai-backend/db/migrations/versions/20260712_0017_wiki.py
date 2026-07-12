"""org wiki entries + revisions (curated context layer)

Revision ID: 20260712_0017
Revises: 20260712_0016
Create Date: 2026-07-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260712_0017"
down_revision: str | Sequence[str] | None = "20260712_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wiki_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("orgs.id"), nullable=False, index=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="published", index=True),
        sa.Column("origin", sa.String(), nullable=False, server_default="manual"),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "wiki_revisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("entry_id", sa.String(), sa.ForeignKey("wiki_entries.id"), nullable=False, index=True),
        sa.Column("org_id", sa.String(), nullable=False, index=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("wiki_revisions")
    op.drop_table("wiki_entries")
