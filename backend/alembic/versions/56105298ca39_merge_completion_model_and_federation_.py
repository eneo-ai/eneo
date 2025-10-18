"""merge completion model and federation heads
Revision ID: 56105298ca39
Revises: 2b3c4d5e6f7a, add_slug_federation
Create Date: 2025-10-18 14:36:10.658497
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = '56105298ca39'
down_revision = ('2b3c4d5e6f7a', 'add_slug_federation')
branch_labels = None
depends_on = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass