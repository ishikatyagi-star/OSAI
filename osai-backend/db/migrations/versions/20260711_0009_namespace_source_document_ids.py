"""Namespace existing source document IDs by organization.

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
    conn = op.get_bind()
    # The original FK was created without ON UPDATE CASCADE. Add it before
    # rewriting primary keys so every chunk remains attached to its source.
    op.drop_constraint("chunks_source_document_id_fkey", "chunks", type_="foreignkey")
    op.create_foreign_key(
        "chunks_source_document_id_fkey",
        "chunks",
        "source_documents",
        ["source_document_id"],
        ["id"],
        onupdate="CASCADE",
    )
    rows = conn.execute(sa.text("SELECT id, org_id FROM source_documents")).fetchall()
    for source_id, org_id in rows:
        prefix = f"{org_id}:"
        if source_id.startswith(prefix):
            continue
        conn.execute(
            sa.text("UPDATE source_documents SET id = :new_id WHERE id = :old_id"),
            {"new_id": f"{prefix}{source_id}", "old_id": source_id},
        )


def downgrade() -> None:
    # IDs are deliberately not collapsed: the pre-migration shape was unsafe.
    pass
