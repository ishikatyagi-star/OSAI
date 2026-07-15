"""Drop the wiki tables — the feature is replaced by Ask's memory.

A user now teaches OSAI a fact by telling Ask ("remember that X"), which writes
straight to org_memory. Published wiki entries were already mirrored into
org_memory (the old _index_for_ask), so the knowledge Ask cites survives this
drop; only the wiki editing surface, its revision history, and unapproved
"suggested" drafts go away.

Revision ID: 20260715_0023
Revises: 20260713_0022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260715_0023"
down_revision: str | Sequence[str] | None = "20260713_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("wiki_revisions")
    op.drop_table("wiki_entries")


def downgrade() -> None:
    op.create_table(
        "wiki_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("orgs.id"), index=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), server_default="published", index=True),
        sa.Column("origin", sa.String(), server_default="manual"),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "wiki_revisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("entry_id", sa.String(), sa.ForeignKey("wiki_entries.id"), index=True),
        sa.Column("org_id", sa.String(), index=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True, index=True),
    )
