"""add updated_at to groups_spaces and websites_spaces

Revision ID: 202610091000
Revises: 202610011100
Create Date: 2026-10-09 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610091000"
down_revision: str = "202610011100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Both junction tables inherit BaseCrossReference, which maps created_at and
# updated_at, but b8a20aead976 and 42f8f8ae0ea7 only created created_at. Every
# other cross-reference table carries both columns.
TABLES = ("groups_spaces", "websites_spaces")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        # Existing rows have never been updated, so their created_at is the
        # truthful value rather than the migration time.
        op.execute(sa.text(f"UPDATE {table} SET updated_at = created_at"))


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_column(table, "updated_at")
