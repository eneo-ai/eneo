"""add favorite_providers to tenants

Revision ID: a1b2c3d4e5f6
Revises: 9d2a6c01f3e7
Create Date: 2026-03-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "b05f080c2656"
down_revision = "9d2a6c01f3e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("favorite_providers", JSONB, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("tenants", "favorite_providers")
