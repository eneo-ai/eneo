"""index File/Icon backfill recovery content lookup

Revision ID: 202608281200
Revises: 202608281130
Create Date: 2026-08-28 12:00:00.000000

Backend verification failures locate adopted File/Icon ledger rows by content
ID. Build that lookup index concurrently because the online backfill may already
have populated the temporary ledger when this revision runs.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202608281200"
down_revision: str | None = "202608281130"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "ix_file_icon_backfill_items_content_id"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # A failed concurrent build can leave an invalid index behind. Dropping
        # it first keeps a retry of this unapplied migration safe.
        op.drop_index(
            _INDEX_NAME,
            table_name="file_icon_backfill_items",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.create_index(
            _INDEX_NAME,
            "file_icon_backfill_items",
            ["content_id"],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            _INDEX_NAME,
            table_name="file_icon_backfill_items",
            if_exists=True,
            postgresql_concurrently=True,
        )
