"""Add a separately declared shared context window.

Revision ID: 202609161000
Revises: 202609151000
"""

import sqlalchemy as sa

from alembic import op

revision = "202609161000"
down_revision = "202609151000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "completion_models",
        sa.Column("context_window_tokens", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("completion_models", "context_window_tokens")
