"""Give a file a home space.

A file row has its owner and its organisation, but no space: the space is
known when the file is made and then dropped, so nothing a space requires can
reach its files.

``files.home_space_id`` is the one space a file belongs in. It is empty for
every existing file and nothing writes it yet. The key to ``spaces`` takes no
action on delete: a space is removed only after the files that have it as
their home, and the home is never emptied by a delete. An organisation is
still removed in one statement, since the check runs when that statement ends.

The column is added without rewriting a row. The key is validated and the
index is built while ``files`` is locked; both read the whole table, where
every home is empty.

Revision ID: 202611261000
Revises: 202611251300
Create Date: 2026-11-26 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202611261000"
down_revision: str = "202611251300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY = "fk_files_home_space_id"
_INDEX = "ix_files_home_space_id"


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column("home_space_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        _KEY,
        "files",
        "spaces",
        ["home_space_id"],
        ["id"],
        postgresql_not_valid=True,
    )
    op.execute(f"ALTER TABLE files VALIDATE CONSTRAINT {_KEY}")
    # Removing a space asks which files have it as their home; without this
    # index that question reads every file.
    op.create_index(
        _INDEX,
        "files",
        ["home_space_id"],
        postgresql_where=sa.text("home_space_id IS NOT NULL"),
    )


def downgrade() -> None:
    # The home is the only record of where a file belongs. Refuse instead of
    # dropping it silently.
    homed = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM files WHERE home_space_id IS NOT NULL"))
        .scalar_one()
    )
    if homed:
        raise RuntimeError(
            f"Cannot remove the home of files: {homed} files have one. "
            "Restore the backup taken before the upgrade instead."
        )
    op.drop_index(_INDEX, table_name="files")
    op.drop_constraint(_KEY, "files", type_="foreignkey")
    op.drop_column("files", "home_space_id")
