"""merge http auth and completion model migrations
Revision ID: 6d9070b60c28
Revises: 2b3c4d5e6f7a, add_http_auth_to_websites
Create Date: 2025-10-13 14:38:36.696467
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = '6d9070b60c28'
down_revision = ('2b3c4d5e6f7a', 'add_http_auth_to_websites')
branch_labels = None
depends_on = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass