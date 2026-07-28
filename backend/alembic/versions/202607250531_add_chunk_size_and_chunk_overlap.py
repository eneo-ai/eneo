"""add chunk_size and chunk_overlap to knowledge source tables

Revision ID: 202607250531
Revises: 202607271100
Create Date: 2026-07-25 05:31:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607250531"
down_revision: str | None = "202607271100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("groups", "websites", "integration_knowledge"):
        op.add_column(table, sa.Column("chunk_size", sa.Integer(), nullable=True))
        op.add_column(table, sa.Column("chunk_overlap", sa.Integer(), nullable=True))


def downgrade() -> None:
    for table in ("groups", "websites", "integration_knowledge"):
        op.drop_column(table, "chunk_overlap")
        op.drop_column(table, "chunk_size")
