"""orgs.slack_ask_token_hash — Slack /ask slash-command tokens

Revision ID: 20260712_0021
Revises: 20260712_0020
Create Date: 2026-07-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260712_0021"
down_revision: str | Sequence[str] | None = "20260712_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orgs", sa.Column("slack_ask_token_hash", sa.String(), nullable=True))
    op.create_index("ix_orgs_slack_ask_token_hash", "orgs", ["slack_ask_token_hash"])


def downgrade() -> None:
    op.drop_index("ix_orgs_slack_ask_token_hash", table_name="orgs")
    op.drop_column("orgs", "slack_ask_token_hash")
