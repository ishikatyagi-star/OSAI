"""answer feedback table

Thumbs up/down + wrong-source flags on Ask answers, stored with the retrieval
trace (citations, scores, model route) — the eval dataset that makes the
retrieval-quality roadmap measurable.

Revision ID: 20260711_0011
Revises: 20260711_0010
Create Date: 2026-07-11
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260711_0011"
down_revision: str | Sequence[str] | None = "20260711_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "answer_feedback",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("orgs.id"), nullable=False, index=True),
        sa.Column("user_id", sa.String(), nullable=True, index=True),
        sa.Column("conversation_id", sa.String(), nullable=True, index=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("rating", sa.String(), nullable=False, index=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("wrong_sources", sa.JSON(), nullable=True),
        sa.Column("retrieval_trace", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("answer_feedback")
