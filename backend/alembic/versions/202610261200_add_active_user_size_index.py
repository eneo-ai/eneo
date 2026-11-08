"""add active info blob user size index

Summing a user's active knowledge size used the plain user index, so users
with long version histories got a bitmap scan over every version. This partial
covering index lets PostgreSQL answer the sum from the index alone.

Revision ID: 202610261200
Revises: 202610191000
Create Date: 2026-10-26 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610261200"
down_revision: str | None = "202610191000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_info_blobs_active_user_size"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        op.create_index(
            _INDEX,
            "info_blobs",
            ["user_id"],
            postgresql_include=["size"],
            postgresql_where=sa.text("version_state = 'active'"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
