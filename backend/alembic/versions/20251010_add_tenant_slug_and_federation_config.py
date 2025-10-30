# flake8: noqa

"""add tenant slug and federation_config

Revision ID: add_slug_federation
Revises: 1604e9b11e38
Create Date: 2025-10-10 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic
revision = 'add_slug_federation'
down_revision = '1604e9b11e38'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add slug and federation_config columns to tenants table with indexes."""
    # Add slug column (VARCHAR(63), unique, nullable for existing tenants)
    op.add_column(
        'tenants',
        sa.Column(
            'slug',
            sa.VARCHAR(63),
            nullable=True  # Nullable to allow backfilling existing tenants
        )
    )

    # Add federation_config JSONB column with default empty JSON object
    op.add_column(
        'tenants',
        sa.Column(
            'federation_config',
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb")
        )
    )

    # Create unique index for slug lookups (partial index to allow NULL values)
    op.create_index(
        'idx_tenants_slug',
        'tenants',
        ['slug'],
        unique=True,
        postgresql_where=sa.text('slug IS NOT NULL')
    )

    # Create GIN index for efficient JSONB queries on federation_config
    op.create_index(
        'idx_tenants_federation_config_gin',
        'tenants',
        ['federation_config'],
        unique=False,
        postgresql_using='gin'
    )


def downgrade() -> None:
    """Remove slug and federation_config columns and their indexes from tenants table."""
    # Drop indexes first
    op.drop_index(
        'idx_tenants_federation_config_gin',
        table_name='tenants'
    )
    op.drop_index(
        'idx_tenants_slug',
        table_name='tenants'
    )

    # Drop columns
    op.drop_column('tenants', 'federation_config')
    op.drop_column('tenants', 'slug')
