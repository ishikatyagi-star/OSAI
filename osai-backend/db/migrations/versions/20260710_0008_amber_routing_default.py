"""align stored amber routing with the UI policy copy

The Amber tier's UI description promises "only Notion and Google Drive", but
the seed default was ["notion", "freshdesk"] (QA ISSUE-005). Fix rows that
still hold the unmodified old default; orgs that customized their routing are
left untouched.

Revision ID: 20260710_0008
Revises: 20260710_0007
Create Date: 2026-07-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260710_0008"
down_revision: str | Sequence[str] | None = "20260710_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ["notion", "freshdesk"]
_NEW = ["notion", "google_drive"]


def upgrade() -> None:
    import json

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, data_routing FROM orgs WHERE data_routing IS NOT NULL")
    ).fetchall()
    for org_id, routing in rows:
        if isinstance(routing, str):
            routing = json.loads(routing)
        amber = (routing or {}).get("amber") or {}
        if amber.get("allowed_connectors") == _OLD:
            routing["amber"] = {**amber, "allowed_connectors": _NEW}
            conn.execute(
                sa.text("UPDATE orgs SET data_routing = :routing WHERE id = :id"),
                {"routing": json.dumps(routing), "id": org_id},
            )


def downgrade() -> None:
    # Data-only fix; no structural change to revert.
    pass
