"""merge_develop_audit_migrations
Revision ID: d5a731604652
Revises: 20251121_set_embedding_org, d5c001343e52
Create Date: 2025-11-26 07:24:48.005458
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = 'd5a731604652'
down_revision = ('20251121_set_embedding_org', 'd5c001343e52')
branch_labels = None
depends_on = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass