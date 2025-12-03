# flake8: noqa

"""Add tenant-scoped template management for Assistants and Apps.

This migration consolidates all template enhancements into a single migration:
- Tenant scoping (tenant_id, soft delete with deleted_at, original_snapshot)
- Audit tracking (deleted_by, restored_by, restored_at)
- Default templates (is_default flag)
- Icon support (icon_name for Lucide icons)
- Feature flag (using_templates)

Revision ID: tenant_scoped_templates
Revises: 3914e3c83f18
Create Date: 2025-10-27 12:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic
revision = 'tenant_scoped_templates'
down_revision = '3914e3c83f18'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add comprehensive tenant-scoped template management."""

    # ============================================================================
    # ASSISTANT_TEMPLATES
    # ============================================================================

    # Add tenant scoping columns
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

    # Add audit tracking columns
    op.add_column(
        'assistant_templates',
        sa.Column('deleted_by_user_id', sa.UUID(), nullable=True)
    )
    op.add_column(
        'assistant_templates',
        sa.Column('restored_by_user_id', sa.UUID(), nullable=True)
    )
    op.add_column(
        'assistant_templates',
        sa.Column('restored_at', sa.TIMESTAMP(timezone=True), nullable=True)
    )

    # Add default template flag
    op.add_column(
        'assistant_templates',
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false')
    )

    # Add icon support
    op.add_column(
        'assistant_templates',
        sa.Column('icon_name', sa.String(100), nullable=True)
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
        'fk_assistant_templates_deleted_by',
        'assistant_templates',
        'users',
        ['deleted_by_user_id'],
        ['id'],
        ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_assistant_templates_restored_by',
        'assistant_templates',
        'users',
        ['restored_by_user_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # Create indexes
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
    op.create_index(
        'ix_assistant_templates_deleted_by',
        'assistant_templates',
        ['deleted_by_user_id']
    )
    op.create_index(
        'ix_assistant_templates_restored_by',
        'assistant_templates',
        ['restored_by_user_id']
    )
    op.create_index(
        'ix_assistant_templates_is_default',
        'assistant_templates',
        ['is_default']
    )
    op.create_index(
        'ix_assistant_templates_icon_name',
        'assistant_templates',
        ['icon_name']
    )

    # Add unique constraint for name+tenant_id (prevents race condition duplicates)
    op.create_index(
        'uq_assistant_templates_name_tenant',
        'assistant_templates',
        ['name', 'tenant_id'],
        unique=True,
        postgresql_where=sa.text('deleted_at IS NULL')
    )

    # ============================================================================
    # APP_TEMPLATES
    # ============================================================================

    # Add tenant scoping columns
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

    # Add audit tracking columns
    op.add_column(
        'app_templates',
        sa.Column('deleted_by_user_id', sa.UUID(), nullable=True)
    )
    op.add_column(
        'app_templates',
        sa.Column('restored_by_user_id', sa.UUID(), nullable=True)
    )
    op.add_column(
        'app_templates',
        sa.Column('restored_at', sa.TIMESTAMP(timezone=True), nullable=True)
    )

    # Add default template flag
    op.add_column(
        'app_templates',
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false')
    )

    # Add icon support
    op.add_column(
        'app_templates',
        sa.Column('icon_name', sa.String(100), nullable=True)
    )

    # Add foreign key constraints
    op.create_foreign_key(
        'fk_app_templates_tenant_id',
        'app_templates',
        'tenants',
        ['tenant_id'],
        ['id'],
        ondelete='CASCADE'
    )
    op.create_foreign_key(
        'fk_app_templates_deleted_by',
        'app_templates',
        'users',
        ['deleted_by_user_id'],
        ['id'],
        ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_app_templates_restored_by',
        'app_templates',
        'users',
        ['restored_by_user_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # Create indexes
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
    op.create_index(
        'ix_app_templates_deleted_by',
        'app_templates',
        ['deleted_by_user_id']
    )
    op.create_index(
        'ix_app_templates_restored_by',
        'app_templates',
        ['restored_by_user_id']
    )
    op.create_index(
        'ix_app_templates_is_default',
        'app_templates',
        ['is_default']
    )
    op.create_index(
        'ix_app_templates_icon_name',
        'app_templates',
        ['icon_name']
    )

    # Add unique constraint for name+tenant_id (prevents race condition duplicates)
    op.create_index(
        'uq_app_templates_name_tenant',
        'app_templates',
        ['name', 'tenant_id'],
        unique=True,
        postgresql_where=sa.text('deleted_at IS NULL')
    )

    # ============================================================================
    # FEATURE FLAG
    # ============================================================================

    # Create the using_templates feature flag
    op.execute("""
        INSERT INTO global_feature_flags (id, name, description, enabled, created_at, updated_at)
        VALUES (gen_random_uuid(), 'using_templates',
            'Enable tenant-scoped template management for Assistants and Apps',
            false, now(), now())
    """)


def downgrade() -> None:
    """Remove tenant-scoped template management."""

    # Delete feature flag
    op.execute("""
        DELETE FROM global_feature_flags WHERE name = 'using_templates'
    """)

    # ============================================================================
    # APP_TEMPLATES - Drop in reverse order
    # ============================================================================

    # Drop unique constraint
    op.drop_index('uq_app_templates_name_tenant', table_name='app_templates')

    # Drop indexes
    op.drop_index('ix_app_templates_icon_name', table_name='app_templates')
    op.drop_index('ix_app_templates_is_default', table_name='app_templates')
    op.drop_index('ix_app_templates_restored_by', table_name='app_templates')
    op.drop_index('ix_app_templates_deleted_by', table_name='app_templates')
    op.drop_index('ix_app_templates_tenant_deleted', table_name='app_templates')
    op.drop_index('ix_app_templates_deleted_at', table_name='app_templates')
    op.drop_index('ix_app_templates_tenant_id', table_name='app_templates')

    # Drop foreign key constraints
    op.drop_constraint('fk_app_templates_restored_by', 'app_templates', type_='foreignkey')
    op.drop_constraint('fk_app_templates_deleted_by', 'app_templates', type_='foreignkey')
    op.drop_constraint('fk_app_templates_tenant_id', 'app_templates', type_='foreignkey')

    # Drop columns
    op.drop_column('app_templates', 'icon_name')
    op.drop_column('app_templates', 'is_default')
    op.drop_column('app_templates', 'restored_at')
    op.drop_column('app_templates', 'restored_by_user_id')
    op.drop_column('app_templates', 'deleted_by_user_id')
    op.drop_column('app_templates', 'original_snapshot')
    op.drop_column('app_templates', 'deleted_at')
    op.drop_column('app_templates', 'tenant_id')

    # ============================================================================
    # ASSISTANT_TEMPLATES - Drop in reverse order
    # ============================================================================

    # Drop unique constraint
    op.drop_index('uq_assistant_templates_name_tenant', table_name='assistant_templates')

    # Drop indexes
    op.drop_index('ix_assistant_templates_icon_name', table_name='assistant_templates')
    op.drop_index('ix_assistant_templates_is_default', table_name='assistant_templates')
    op.drop_index('ix_assistant_templates_restored_by', table_name='assistant_templates')
    op.drop_index('ix_assistant_templates_deleted_by', table_name='assistant_templates')
    op.drop_index('ix_assistant_templates_tenant_deleted', table_name='assistant_templates')
    op.drop_index('ix_assistant_templates_deleted_at', table_name='assistant_templates')
    op.drop_index('ix_assistant_templates_tenant_id', table_name='assistant_templates')

    # Drop foreign key constraints
    op.drop_constraint('fk_assistant_templates_restored_by', 'assistant_templates', type_='foreignkey')
    op.drop_constraint('fk_assistant_templates_deleted_by', 'assistant_templates', type_='foreignkey')
    op.drop_constraint('fk_assistant_templates_tenant_id', 'assistant_templates', type_='foreignkey')

    # Drop columns
    op.drop_column('assistant_templates', 'icon_name')
    op.drop_column('assistant_templates', 'is_default')
    op.drop_column('assistant_templates', 'restored_at')
    op.drop_column('assistant_templates', 'restored_by_user_id')
    op.drop_column('assistant_templates', 'deleted_by_user_id')
    op.drop_column('assistant_templates', 'original_snapshot')
    op.drop_column('assistant_templates', 'deleted_at')
    op.drop_column('assistant_templates', 'tenant_id')
