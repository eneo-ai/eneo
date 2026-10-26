"""index icon references

Deleting an icon first checks that no assistant, app, space or group chat
still references it, and the ``ON DELETE SET NULL`` foreign keys look the same
columns up again. Without an index each of those lookups reads the whole table.
Most rows have no icon, so the indexes are partial.

The tables are small, so the indexes are built inside the migration
transaction instead of ``CONCURRENTLY``.

Revision ID: 202610261220
Revises: 202610261210
Create Date: 2026-10-26 12:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610261220"
down_revision: str | None = "202610261210"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("assistants", "apps", "spaces", "group_chats")


def upgrade() -> None:
    for table in _TABLES:
        op.create_index(
            f"ix_{table}_icon_id",
            table,
            ["icon_id"],
            postgresql_where=sa.text("icon_id IS NOT NULL"),
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_index(f"ix_{table}_icon_id", table_name=table)
