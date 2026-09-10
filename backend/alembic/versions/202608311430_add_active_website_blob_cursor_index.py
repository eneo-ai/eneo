"""add active website info blob cursor index

Revision ID: 202608311430
Revises: 202608311400
Create Date: 2026-08-31 14:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608311430"
down_revision: str | None = "202608311400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_info_blobs_active_website_cursor"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        op.create_index(
            _INDEX,
            "info_blobs",
            ["website_id", "id"],
            postgresql_where=sa.text("version_state = 'active'"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
