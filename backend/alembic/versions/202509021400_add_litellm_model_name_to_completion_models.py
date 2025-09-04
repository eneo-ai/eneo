"""add_litellm_model_name_to_completion_models

Revision ID: a1b2c3d4e5f6
Revises: 1e58cb567f44
Create Date: 2025-09-02 14:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '1e58cb567f44'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add litellm_model_name column to completion_models table
    op.add_column(
        'completion_models', sa.Column('litellm_model_name', sa.String(), nullable=True)
    )


def downgrade() -> None:
    # Remove litellm_model_name column from completion_models table
    op.drop_column('completion_models', 'litellm_model_name')