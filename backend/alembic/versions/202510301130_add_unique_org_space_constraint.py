"""Add unique constraint to prevent duplicate org spaces

Revision ID: 202510301130
Revises: c4af97fb702d
Create Date: 2025-10-30 11:30:00.000000

Ensures only one organization space can exist per tenant by creating a partial unique index.
This prevents race conditions when multiple requests try to create an org space simultaneously.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision = '202510301130'
down_revision = 'c4af97fb702d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add unique constraint for organization spaces."""
    op.create_index(
        'idx_unique_org_space_per_tenant',
        'spaces',
        ['tenant_id'],
        unique=True,
        postgresql_where=sa.text('user_id IS NULL AND tenant_space_id IS NULL')
    )


def downgrade() -> None:
    """Remove unique constraint for organization spaces."""
    op.drop_index('idx_unique_org_space_per_tenant')
