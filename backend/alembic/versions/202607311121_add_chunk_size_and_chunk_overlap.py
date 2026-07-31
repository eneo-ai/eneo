"""add chunk_size and chunk_overlap to knowledge sources and info blobs

The knowledge source tables carry the configuration a user asked for. ``info_blobs``
carries the effective values the stored material was actually chunked with, which is
what lets a re-crawl tell whether existing material is stale. NULL on an info blob
means "chunked before this column existed" and deliberately never counts as a
mismatch, so upgrading cannot trigger a mass re-index.

Revision ID: 202607311121
Revises: 202607301200
Create Date: 2026-07-31 11:21:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607311121"
down_revision: str | None = "202607301200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Requested configuration, per knowledge source.
    for table in ("groups", "websites", "integration_knowledge"):
        op.add_column(table, sa.Column("chunk_size", sa.Integer(), nullable=True))
        op.add_column(table, sa.Column("chunk_overlap", sa.Integer(), nullable=True))

    # Effective values the stored chunks were produced with. Nullable and left
    # unbackfilled: pre-existing blobs were chunked with unknown settings, and
    # guessing would make the stale check re-index them all on the next crawl.
    op.add_column("info_blobs", sa.Column("chunk_size", sa.Integer(), nullable=True))
    op.add_column("info_blobs", sa.Column("chunk_overlap", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("info_blobs", "chunk_overlap")
    op.drop_column("info_blobs", "chunk_size")

    for table in ("groups", "websites", "integration_knowledge"):
        op.drop_column(table, "chunk_overlap")
        op.drop_column(table, "chunk_size")
