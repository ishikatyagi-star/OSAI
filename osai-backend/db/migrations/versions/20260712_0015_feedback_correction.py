"""answer_feedback.correction column

The user's stated correct answer on a thumbs-down; persisted alongside the
trace and mirrored into org memory as a team-wide correction.

Revision ID: 20260712_0015
Revises: 20260711_0014
Create Date: 2026-07-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260712_0015"
down_revision: str | Sequence[str] | None = "20260711_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("answer_feedback", sa.Column("correction", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("answer_feedback", "correction")
