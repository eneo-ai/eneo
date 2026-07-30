"""add cursor index for paged personal-default validation

Revision ID: 202607281340
Revises: 202607271100
Create Date: 2026-07-28 13:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607281340"
down_revision: str | None = "202607271100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_assistants_default_created_at_id"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # A failed concurrent build can leave an invalid index behind. Dropping
        # it first keeps a retry of this unapplied migration safe.
        op.drop_index(
            _INDEX,
            table_name="assistants",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.create_index(
            _INDEX,
            "assistants",
            ["created_at", "id"],
            postgresql_where=sa.text("is_default = true"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            _INDEX,
            table_name="assistants",
            if_exists=True,
            postgresql_concurrently=True,
        )
