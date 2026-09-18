"""Count widget visitors' thumbs up and down per day.

Revision ID: 202609181000
Revises: 202609171600
"""

import sqlalchemy as sa

from alembic import op

revision = "202609181000"
down_revision = "202609171600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "widget_daily_usage",
        sa.Column("helpful", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "widget_daily_usage",
        sa.Column("unhelpful", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("widget_daily_usage", "unhelpful")
    op.drop_column("widget_daily_usage", "helpful")
