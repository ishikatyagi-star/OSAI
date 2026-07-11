"""make seeded ownership memories org-wide

Org-memory recall now treats `user_id` as a visibility scope (private to that
user). Seeded ownership facts ("alice owns task X") stored the task owner in
user_id as a *subject* reference, which under the new rule would hide them
from everyone except the owner. Ownership facts are org-wide knowledge, so
clear their user_id; genuinely private memories (none written with this kind)
are untouched.

Revision ID: 20260711_0009
Revises: 20260710_0008
Create Date: 2026-07-11
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260711_0009"
down_revision: str | Sequence[str] | None = "20260710_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE org_memory SET user_id = NULL WHERE kind = 'ownership'")
    )


def downgrade() -> None:
    # The old owner value lives in the memory content; nothing to restore.
    pass
