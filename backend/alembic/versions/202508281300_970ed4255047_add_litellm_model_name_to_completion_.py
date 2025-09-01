"""add_litellm_model_name_to_completion_models
Revision ID: 970ed4255047
Revises: 1e58cb567f44
Create Date: 2025-08-28 13:33:45.744862
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = '970ed4255047'
down_revision = '1e58cb567f44'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add litellm_model_name column to CompletionModels table
    op.add_column('completion_models', sa.Column('litellm_model_name', sa.String(), nullable=True))


def downgrade() -> None:
    # Remove litellm_model_name column from CompletionModels table
    op.drop_column('completion_models', 'litellm_model_name')
