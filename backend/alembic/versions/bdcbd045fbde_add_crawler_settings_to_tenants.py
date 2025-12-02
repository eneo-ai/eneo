"""Add crawler_settings JSONB column to tenants table.

Revision ID: bdcbd045fbde
Revises: 20251121_set_embedding_org
Create Date: 2025-11-24

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "bdcbd045fbde"
down_revision = "20251121_set_embedding_org"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("crawler_settings", JSONB(), server_default="{}", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("tenants", "crawler_settings")
