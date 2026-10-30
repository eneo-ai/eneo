"""Discard the separate context window, preserving declared input/output limits.

Revision ID: 202609171100
Revises: 202609161100
"""

import sqlalchemy as sa

from alembic import op

revision = "202609171100"
down_revision = "202609161100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("completion_models", "context_window_tokens")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "completion_models",
        sa.Column("context_window_tokens", sa.Integer(), nullable=True),
    )
