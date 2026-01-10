"""add_onedrive_support

Add resource_type and drive_id columns to integration_knowledge table
to support OneDrive for Business alongside SharePoint sites.

resource_type: 'site' (default) for SharePoint sites, 'onedrive' for OneDrive
drive_id: Direct drive ID for OneDrive (bypasses site lookup)

Revision ID: 202512041200
Revises: 7e4f8a9c5d12
Create Date: 2025-12-04 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = '202512041200'
down_revision = '7e4f8a9c5d12'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add resource_type column with default 'site' for backward compatibility
    op.add_column(
        'integration_knowledge',
        sa.Column('resource_type', sa.Text(), nullable=True, server_default='site')
    )

    # Add drive_id column for direct OneDrive access (no site_id needed)
    op.add_column(
        'integration_knowledge',
        sa.Column('drive_id', sa.Text(), nullable=True)
    )

    # Create index on resource_type for efficient filtering
    op.create_index(
        op.f('ix_integration_knowledge_resource_type'),
        'integration_knowledge',
        ['resource_type'],
        unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_integration_knowledge_resource_type'), table_name='integration_knowledge')
    op.drop_column('integration_knowledge', 'drive_id')
    op.drop_column('integration_knowledge', 'resource_type')
