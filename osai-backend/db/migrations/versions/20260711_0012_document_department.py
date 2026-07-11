"""department attribution on source documents

Documents can belong to an org department, enabling department-scoped
retrieval ("Ask Engineering") and department digests. Existing documents stay
org-wide (NULL).

Revision ID: 20260711_0012
Revises: 20260711_0011
Create Date: 2026-07-11
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260711_0012"
down_revision: str | Sequence[str] | None = "20260711_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_documents", sa.Column("department_id", sa.String(), nullable=True)
    )
    op.create_index(
        "ix_source_documents_department_id", "source_documents", ["department_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_source_documents_department_id", table_name="source_documents")
    op.drop_column("source_documents", "department_id")
