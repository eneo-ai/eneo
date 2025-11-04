"""remove unique constraint on model names

Revision ID: 20251104_remove_unique
Revises: c24c8d895bcd
Create Date: 2025-11-04

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '20251104_remove_unique'
down_revision = 'c24c8d895bcd'
branch_labels = None
depends_on = None


def upgrade():
    # Drop unique constraints on name fields
    # This allows the same model name to exist from different providers
    op.drop_constraint('completion_models_name_key', 'completion_models', type_='unique')
    op.drop_constraint('embedding_models_name_key', 'embedding_models', type_='unique')
    op.drop_constraint('transcription_models_name_key', 'transcription_models', type_='unique')


def downgrade():
    # Restore unique constraints
    # Note: This will fail if duplicate names exist in the database
    op.create_unique_constraint('completion_models_name_key', 'completion_models', ['name'])
    op.create_unique_constraint('embedding_models_name_key', 'embedding_models', ['name'])
    op.create_unique_constraint('transcription_models_name_key', 'transcription_models', ['name'])
