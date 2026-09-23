"""Let a widget keep its tool activity out of the visitor's view.

Revision ID: 202609231500
Revises: 202609221000
"""

import sqlalchemy as sa

from alembic import op

revision = "202609231500"
down_revision = "202609221000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "widgets",
        sa.Column(
            "show_tool_activity",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("widgets", "show_tool_activity")
