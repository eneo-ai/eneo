# flake8: noqa

"""add sharepoint subscription columns
Revision ID: 202502201330
Revises: 5b8d3d2c51ae
Create Date: 2025-02-20 13:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = "202502201330"
down_revision = "5b8d3d2c51ae"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integration_knowledge",
        sa.Column("sharepoint_subscription_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "integration_knowledge",
        sa.Column("sharepoint_subscription_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("integration_knowledge", "sharepoint_subscription_expires_at")
    op.drop_column("integration_knowledge", "sharepoint_subscription_id")
