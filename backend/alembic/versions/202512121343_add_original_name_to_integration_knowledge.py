"""add_original_name_to_integration_knowledge

Add original_name column to integration_knowledge table to store the original
name from SharePoint/Confluence. This allows users to rename the knowledge
while preserving the original name for reference.

Revision ID: 202512121343
Revises: 202512111200
Create Date: 2025-12-12 13:43:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = '202512121343'
down_revision = '202512111200'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add original_name column
    op.add_column(
        'integration_knowledge',
        sa.Column('original_name', sa.Text(), nullable=True)
    )

    # Populate original_name from existing name values for existing records
    op.execute("UPDATE integration_knowledge SET original_name = name WHERE original_name IS NULL")


def downgrade() -> None:
    op.drop_column('integration_knowledge', 'original_name')
