# flake8: noqa

"""add sync metadata to integration knowledge
Revision ID: 5b8d3d2c51ae
Revises: 2b3c4d5e6f7a
Create Date: 2025-02-20 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic
revision = "5b8d3d2c51ae"
down_revision = "2b3c4d5e6f7a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integration_knowledge",
        sa.Column("last_synced_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "integration_knowledge",
        sa.Column(
            "last_sync_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "integration_knowledge",
        sa.Column("site_id", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("integration_knowledge", "site_id")
    op.drop_column("integration_knowledge", "last_sync_summary")
    op.drop_column("integration_knowledge", "last_synced_at")
