# flake8: noqa

"""Add audit tracking fields to template tables (deleted_by, restored_by, restored_at).

Revision ID: add_template_audit_fields
Revises: add_tenant_templates_settings
Create Date: 2025-10-28 12:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = 'add_template_audit_fields'
down_revision = 'add_tenant_templates_settings'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add audit tracking fields for delete/restore operations."""

    # Add audit columns to assistant_templates
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

    # Add audit columns to app_templates
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

    # Add foreign key constraints for audit fields
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

    # Add indexes for audit queries (who deleted what, who restored what)
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
        'ix_app_templates_deleted_by',
        'app_templates',
        ['deleted_by_user_id']
    )
    op.create_index(
        'ix_app_templates_restored_by',
        'app_templates',
        ['restored_by_user_id']
    )


def downgrade() -> None:
    """Remove audit tracking fields."""

    # Drop indexes for app_templates
    op.drop_index('ix_app_templates_restored_by', table_name='app_templates')
    op.drop_index('ix_app_templates_deleted_by', table_name='app_templates')

    # Drop indexes for assistant_templates
    op.drop_index('ix_assistant_templates_restored_by', table_name='assistant_templates')
    op.drop_index('ix_assistant_templates_deleted_by', table_name='assistant_templates')

    # Drop foreign key constraints for app_templates
    op.drop_constraint('fk_app_templates_restored_by', 'app_templates', type_='foreignkey')
    op.drop_constraint('fk_app_templates_deleted_by', 'app_templates', type_='foreignkey')

    # Drop foreign key constraints for assistant_templates
    op.drop_constraint('fk_assistant_templates_restored_by', 'assistant_templates', type_='foreignkey')
    op.drop_constraint('fk_assistant_templates_deleted_by', 'assistant_templates', type_='foreignkey')

    # Drop columns from app_templates
    op.drop_column('app_templates', 'restored_at')
    op.drop_column('app_templates', 'restored_by_user_id')
    op.drop_column('app_templates', 'deleted_by_user_id')

    # Drop columns from assistant_templates
    op.drop_column('assistant_templates', 'restored_at')
    op.drop_column('assistant_templates', 'restored_by_user_id')
    op.drop_column('assistant_templates', 'deleted_by_user_id')
