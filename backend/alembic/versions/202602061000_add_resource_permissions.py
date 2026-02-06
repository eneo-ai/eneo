"""add resource_permissions column to api_keys_v2

Revision ID: 202602061000
Revises: 202602051000
Create Date: 2026-02-06 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic
revision = "202602061000"
down_revision = "202602051000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_keys_v2",
        sa.Column("resource_permissions", JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("api_keys_v2", "resource_permissions")
