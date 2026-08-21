"""merge migration heads
Revision ID: 5d05830c60be
Revises: 202607311121, 202608041200, 202608181000
Create Date: 2026-08-21 11:12:57.628451
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = '5d05830c60be'
down_revision = ('202607311121', '202608041200', '202608181000')
branch_labels = None
depends_on = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass