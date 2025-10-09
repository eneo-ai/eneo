# flake8: noqa

"""add tenant api_credentials

Revision ID: 1604e9b11e38
Revises: da3ec8750c0a
Create Date: 2025-10-07 12:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic
revision = '1604e9b11e38'
down_revision = '2f8e9a1b3c5d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add api_credentials JSONB column to tenants table with GIN index."""
    # Add api_credentials column with NOT NULL constraint and default empty JSON object
    op.add_column(
        'tenants',
        sa.Column(
            'api_credentials',
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb")
        )
    )

    # Create GIN index for efficient JSONB queries
    op.create_index(
        'idx_tenants_api_credentials_gin',
        'tenants',
        ['api_credentials'],
        unique=False,
        postgresql_using='gin'
    )


def downgrade() -> None:
    """Remove api_credentials column and its GIN index from tenants table."""
    # Drop index first
    op.drop_index(
        'idx_tenants_api_credentials_gin',
        table_name='tenants'
    )

    # Drop column
    op.drop_column('tenants', 'api_credentials')
