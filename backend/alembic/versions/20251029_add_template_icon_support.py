# flake8: noqa

"""Add icon support to template tables using Lucide icon names.

Revision ID: add_template_icon_support
Revises: add_template_defaults
Create Date: 2025-10-29 14:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = 'add_template_icon_support'
down_revision = 'add_template_defaults'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add icon_name column to template tables for Lucide icons."""

    # Add icon_name column to assistant_templates
    op.add_column(
        'assistant_templates',
        sa.Column('icon_name', sa.String(100), nullable=True)
    )

    # Add icon_name column to app_templates
    op.add_column(
        'app_templates',
        sa.Column('icon_name', sa.String(100), nullable=True)
    )

    # Add indexes for efficient icon filtering/display
    op.create_index(
        'ix_assistant_templates_icon_name',
        'assistant_templates',
        ['icon_name']
    )

    op.create_index(
        'ix_app_templates_icon_name',
        'app_templates',
        ['icon_name']
    )


def downgrade() -> None:
    """Remove icon support from template tables."""

    # Drop indexes
    op.drop_index('ix_app_templates_icon_name', table_name='app_templates')
    op.drop_index('ix_assistant_templates_icon_name', table_name='assistant_templates')

    # Drop columns
    op.drop_column('app_templates', 'icon_name')
    op.drop_column('assistant_templates', 'icon_name')
