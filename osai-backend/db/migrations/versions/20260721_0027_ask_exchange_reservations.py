"""durable Ask request reservations

Revision ID: 20260721_0027
Revises: 20260721_0026
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0027"
down_revision: str | Sequence[str] | None = "20260721_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ask_exchanges",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("requested_thread_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("lease_id", sa.String(length=36), nullable=False),
        sa.Column("response", sa.JSON(), nullable=True),
        sa.Column("thread_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "org_id", "user_id", "request_id", name="uq_ask_exchanges_request"
        ),
    )
    op.create_index("ix_ask_exchanges_org_id", "ask_exchanges", ["org_id"])
    op.create_index("ix_ask_exchanges_user_id", "ask_exchanges", ["user_id"])
    op.create_index("ix_ask_exchanges_status", "ask_exchanges", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ask_exchanges_status", table_name="ask_exchanges")
    op.drop_index("ix_ask_exchanges_user_id", table_name="ask_exchanges")
    op.drop_index("ix_ask_exchanges_org_id", table_name="ask_exchanges")
    op.drop_table("ask_exchanges")
