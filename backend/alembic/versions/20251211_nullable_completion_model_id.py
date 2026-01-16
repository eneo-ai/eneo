"""Make completion_model_id nullable on apps table

Allow apps to be created without a completion model.
The app will be in a "locked" state until a model is configured.

Revision ID: nullable_app_completion_model
Revises: consolidate_model_settings
Create Date: 2025-12-11
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = 'nullable_app_completion_model'
down_revision = 'consolidate_model_settings'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make completion_model_id nullable on apps table
    op.alter_column(
        'apps',
        'completion_model_id',
        existing_type=sa.UUID(),
        nullable=True
    )


def downgrade() -> None:
    # Revert to NOT NULL - will fail if any NULL values exist
    op.alter_column(
        'apps',
        'completion_model_id',
        existing_type=sa.UUID(),
        nullable=False
    )
