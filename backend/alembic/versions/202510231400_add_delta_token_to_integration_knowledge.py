# flake8: noqa

"""add delta_token to integration_knowledge
Revision ID: 202510231400
Revises: 202502201330
Create Date: 2025-10-23 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = "202510231400"
down_revision = "202502201330"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integration_knowledge",
        sa.Column("delta_token", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("integration_knowledge", "delta_token")
