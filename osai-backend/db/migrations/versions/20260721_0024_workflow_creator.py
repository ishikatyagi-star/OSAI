"""Persist workflow creator for resource-level authorization.

Revision ID: 20260721_0024
Revises: 20260715_0023
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0024"
down_revision: str | Sequence[str] | None = "20260715_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("created_by", sa.String(), nullable=True))
    op.create_index(
        op.f("ix_workflow_runs_created_by"),
        "workflow_runs",
        ["created_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_workflow_runs_created_by"), table_name="workflow_runs")
    op.drop_column("workflow_runs", "created_by")
