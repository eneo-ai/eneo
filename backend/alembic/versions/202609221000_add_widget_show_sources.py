"""Let a widget hide the sources behind its answers.

Revision ID: 202609221000
Revises: 202609211000
"""

import sqlalchemy as sa

from alembic import op

revision = "202609221000"
down_revision = "202609211000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "widgets",
        sa.Column(
            "show_sources", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )


def downgrade() -> None:
    op.drop_column("widgets", "show_sources")
