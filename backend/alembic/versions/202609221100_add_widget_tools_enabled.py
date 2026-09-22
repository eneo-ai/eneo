"""Let a widget expose the assistant's tools to visitors.

Revision ID: 202609221100
Revises: 202609221000
"""

import sqlalchemy as sa

from alembic import op

revision = "202609221100"
down_revision = "202609221000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "widgets",
        sa.Column(
            "tools_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )


def downgrade() -> None:
    op.drop_column("widgets", "tools_enabled")
