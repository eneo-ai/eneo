"""remove_modules_system

Removes the entire module system infrastructure including:
- tenants_modules junction table
- modules table

This eliminates the need for tenants to have specific modules
(EU_HOSTING, SWE_HOSTING, INTRIC_APPLICATIONS) to access certain features.

Revision ID: a5a63c61951d
Revises: bdcbd045fbde
Create Date: 2025-11-26 12:52:36.195255
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = 'a5a63c61951d'
down_revision = 'bdcbd045fbde'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Drop tenants_modules first (has FK to modules)
    op.drop_table('tenants_modules')
    # Then drop modules table
    op.drop_table('modules')

def downgrade() -> None:
    # Recreate modules table
    op.create_table(
        'modules',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column(
            'created_at',
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    # Recreate tenants_modules junction table
    op.create_table(
        'tenants_modules',
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('module_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['module_id'], ['modules.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('tenant_id', 'module_id'),
    )