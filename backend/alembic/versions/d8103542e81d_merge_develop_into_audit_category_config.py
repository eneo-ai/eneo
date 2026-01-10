"""merge_develop_into_audit_category_config
Revision ID: d8103542e81d
Revises: 628250c396ae, 8d909e51b83b
Create Date: 2026-01-10 11:59:27.262868
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = 'd8103542e81d'
down_revision = ('628250c396ae', '8d909e51b83b')
branch_labels = None
depends_on = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass