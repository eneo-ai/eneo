# flake8: noqa

"""Add tenant_id, deleted_at, and original_snapshot to templates. Add using_templates feature flag.

Revision ID: add_tenant_templates_settings
Revises: 3914e3c83f18
Create Date: 2025-10-27 12:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic
revision = 'add_tenant_templates_settings'
down_revision = '3914e3c83f18'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add tenant_id, deleted_at, and original_snapshot columns to template tables."""

    # Add columns to assistant_templates
    op.add_column(
        'assistant_templates',
        sa.Column('tenant_id', sa.UUID(), nullable=True)
    )
    op.add_column(
        'assistant_templates',
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True), nullable=True)
    )
    op.add_column(
        'assistant_templates',
        sa.Column('original_snapshot', JSONB(astext_type=sa.Text()), nullable=True)
    )

    # Add columns to app_templates
    op.add_column(
        'app_templates',
        sa.Column('tenant_id', sa.UUID(), nullable=True)
    )
    op.add_column(
        'app_templates',
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True), nullable=True)
    )
    op.add_column(
        'app_templates',
        sa.Column('original_snapshot', JSONB(astext_type=sa.Text()), nullable=True)
    )

    # Add foreign key constraints
    op.create_foreign_key(
        'fk_assistant_templates_tenant_id',
        'assistant_templates',
        'tenants',
        ['tenant_id'],
        ['id'],
        ondelete='CASCADE'
    )
    op.create_foreign_key(
        'fk_app_templates_tenant_id',
        'app_templates',
        'tenants',
        ['tenant_id'],
        ['id'],
        ondelete='CASCADE'
    )

    # Create indexes for assistant_templates
    op.create_index(
        'ix_assistant_templates_tenant_id',
        'assistant_templates',
        ['tenant_id']
    )
    op.create_index(
        'ix_assistant_templates_deleted_at',
        'assistant_templates',
        ['deleted_at']
    )
    op.create_index(
        'ix_assistant_templates_tenant_deleted',
        'assistant_templates',
        ['tenant_id', 'deleted_at']
    )

    # Create indexes for app_templates
    op.create_index(
        'ix_app_templates_tenant_id',
        'app_templates',
        ['tenant_id']
    )
    op.create_index(
        'ix_app_templates_deleted_at',
        'app_templates',
        ['deleted_at']
    )
    op.create_index(
        'ix_app_templates_tenant_deleted',
        'app_templates',
        ['tenant_id', 'deleted_at']
    )

    # Add unique constraints for name+tenant_id (prevents race condition duplicates)
    op.create_index(
        'uq_assistant_templates_name_tenant',
        'assistant_templates',
        ['name', 'tenant_id'],
        unique=True,
        postgresql_where=sa.text('deleted_at IS NULL')
    )
    op.create_index(
        'uq_app_templates_name_tenant',
        'app_templates',
        ['name', 'tenant_id'],
        unique=True,
        postgresql_where=sa.text('deleted_at IS NULL')
    )

    # Create the using_templates feature flag
    op.execute("""
        INSERT INTO global_feature_flags (id, name, description, enabled, created_at, updated_at)
        VALUES (gen_random_uuid(), 'using_templates',
            'Enable tenant-scoped template management for Assistants and Apps',
            false, now(), now())
    """)


def downgrade() -> None:
    """Remove tenant_id, deleted_at, original_snapshot columns and feature flag."""

    # Delete feature flag
    op.execute("""
        DELETE FROM global_feature_flags WHERE name = 'using_templates'
    """)

    # Drop unique constraints
    op.drop_index('uq_app_templates_name_tenant', table_name='app_templates')
    op.drop_index('uq_assistant_templates_name_tenant', table_name='assistant_templates')

    # Drop indexes for app_templates
    op.drop_index('ix_app_templates_tenant_deleted', table_name='app_templates')
    op.drop_index('ix_app_templates_deleted_at', table_name='app_templates')
    op.drop_index('ix_app_templates_tenant_id', table_name='app_templates')

    # Drop indexes for assistant_templates
    op.drop_index('ix_assistant_templates_tenant_deleted', table_name='assistant_templates')
    op.drop_index('ix_assistant_templates_deleted_at', table_name='assistant_templates')
    op.drop_index('ix_assistant_templates_tenant_id', table_name='assistant_templates')

    # Drop foreign key constraints
    op.drop_constraint('fk_app_templates_tenant_id', 'app_templates', type_='foreignkey')
    op.drop_constraint('fk_assistant_templates_tenant_id', 'assistant_templates', type_='foreignkey')

    # Drop columns from app_templates
    op.drop_column('app_templates', 'original_snapshot')
    op.drop_column('app_templates', 'deleted_at')
    op.drop_column('app_templates', 'tenant_id')

    # Drop columns from assistant_templates
    op.drop_column('assistant_templates', 'original_snapshot')
    op.drop_column('assistant_templates', 'deleted_at')
    op.drop_column('assistant_templates', 'tenant_id')
