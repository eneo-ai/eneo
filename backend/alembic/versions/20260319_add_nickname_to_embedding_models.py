"""add nickname column to embedding models

Revision ID: 20260319_add_nickname
Revises: mcp_security_classification
Create Date: 2026-03-19
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260319_add_nickname"
down_revision = "gc_icon_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add nullable nickname column
    op.add_column(
        "embedding_models",
        sa.Column("nickname", sa.String(), nullable=True),
    )

    # Backfill: extract display name from description for tenant models with the hack pattern
    op.execute(
        """
        UPDATE embedding_models
        SET nickname = SUBSTRING(description FROM 15)
        WHERE description LIKE 'Tenant model: %'
        """
    )

    # Backfill: for all remaining rows without a nickname, use name
    op.execute(
        """
        UPDATE embedding_models
        SET nickname = name
        WHERE nickname IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("embedding_models", "nickname")
