"""change files text column to text type

Revision ID: zcoze86bsbqg
Revises: 20251121_set_embedding_org
Create Date: 2025-11-25 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import Text


# revision identifiers, used by Alembic
revision = 'zcoze86bsbqg'
down_revision = '20251121_set_embedding_org'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Change files.text column from VARCHAR to TEXT to support larger extracted text
    op.alter_column('files', 'text',
                   type_=Text(),
                   existing_type=sa.String())


def downgrade() -> None:
    # Revert back to VARCHAR (may cause data truncation!)
    op.alter_column('files', 'text',
                   type_=sa.String(),
                   existing_type=Text())
