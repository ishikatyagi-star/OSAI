"""automation delivery target + last delivery outcome

Automations can deliver run results to a Slack channel instead of only
storing them in last_result. deliver_to holds the target
({"channel": "slack", "target": "#general"}); last_delivery records the most
recent attempt's outcome so the UI can report failures honestly.

Revision ID: 20260711_0010
Revises: 20260711_0009
Create Date: 2026-07-11
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260711_0010"
down_revision: str | Sequence[str] | None = "20260711_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("automations", sa.Column("deliver_to", sa.JSON(), nullable=True))
    op.add_column("automations", sa.Column("last_delivery", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("automations", "last_delivery")
    op.drop_column("automations", "deliver_to")
