# flake8: noqa

"""Add default configuration field to template tables (is_default).

Revision ID: add_template_defaults
Revises: add_template_audit_fields
Create Date: 2025-10-28 22:30:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = 'add_template_defaults'
down_revision = 'add_template_audit_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add default configuration field for template featuring."""

    # Add is_default column to assistant_templates
    op.add_column(
        'assistant_templates',
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false')
    )

    # Add is_default column to app_templates
    op.add_column(
        'app_templates',
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false')
    )

    # Add indexes for filtering and sorting defaults efficiently
    op.create_index(
        'ix_assistant_templates_is_default',
        'assistant_templates',
        ['is_default']
    )
    op.create_index(
        'ix_app_templates_is_default',
        'app_templates',
        ['is_default']
    )


def downgrade() -> None:
    """Remove default configuration field."""

    # Drop indexes
    op.drop_index('ix_app_templates_is_default', table_name='app_templates')
    op.drop_index('ix_assistant_templates_is_default', table_name='assistant_templates')

    # Drop columns
    op.drop_column('app_templates', 'is_default')
    op.drop_column('assistant_templates', 'is_default')
