"""automations.trigger_token_hash — external trigger API tokens

Revision ID: 20260712_0019
Revises: 20260712_0018
Create Date: 2026-07-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260712_0019"
down_revision: str | Sequence[str] | None = "20260712_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("automations", sa.Column("trigger_token_hash", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("automations", "trigger_token_hash")
