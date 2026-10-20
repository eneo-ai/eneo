"""Persist the current user's postponed release announcement.

Revision ID: 202610201000
Revises: 202610191000
"""

import sqlalchemy as sa

from alembic import op

revision = "202610201000"
down_revision = "202610191000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whats_new_state",
        sa.Column("remind_after", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("whats_new_state", "remind_after")
