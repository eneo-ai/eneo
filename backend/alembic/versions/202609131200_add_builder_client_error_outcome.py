"""add builder client error presentation and first action columns

Revision ID: 202609131200
Revises: 202609081000, 202609111000
Create Date: 2026-09-13 12:00:00.000000

A reported client error learns, after the fact, where and as which class
it was displayed and the user's first explicit selection on it. All
columns are nullable: rows observed before this revision, and rows whose
failure was never acted on, stay valid with nulls.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609131200"
down_revision: str | Sequence[str] | None = ("202609081000", "202609111000")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "builder_client_errors"
COLUMNS = (
    sa.Column("surface", sa.String(length=32), nullable=True),
    sa.Column("presented_as", sa.String(length=64), nullable=True),
    sa.Column("first_action", sa.String(length=64), nullable=True),
    sa.Column("first_action_received_at", sa.TIMESTAMP(timezone=True), nullable=True),
)


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column(TABLE, column)


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column(TABLE, column.name)
