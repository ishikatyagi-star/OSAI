"""action_items fields expansion

Revision ID: 20260604_0002
Revises: 20260604_0001
Create Date: 2026-06-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260604_0002"
down_revision: str | Sequence[str] | None = "20260604_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("action_items", sa.Column("owner", sa.String(), nullable=True))
    op.add_column("action_items", sa.Column("due_date", sa.String(), nullable=True))
    op.add_column("action_items", sa.Column("source_quote", sa.Text(), nullable=True))
    op.add_column("action_items", sa.Column("external_url", sa.Text(), nullable=True))
    op.add_column("action_items", sa.Column("executed_at", sa.DateTime(), nullable=True))
    # Change confidence from Integer to Float (SQLite ALTER is limited; use batch mode)
    with op.batch_alter_table("action_items") as batch_op:
        batch_op.alter_column("confidence", type_=sa.Float(), existing_type=sa.Integer())


def downgrade() -> None:
    with op.batch_alter_table("action_items") as batch_op:
        batch_op.alter_column("confidence", type_=sa.Integer(), existing_type=sa.Float())
    op.drop_column("action_items", "executed_at")
    op.drop_column("action_items", "external_url")
    op.drop_column("action_items", "source_quote")
    op.drop_column("action_items", "due_date")
    op.drop_column("action_items", "owner")
