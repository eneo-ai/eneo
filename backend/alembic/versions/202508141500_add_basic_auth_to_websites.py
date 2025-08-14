"""add basic auth to websites

Revision ID: 202508141500
Revises: 1e58cb567f44
Create Date: 2025-08-14 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '202508141500'
down_revision = '1e58cb567f44'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add basic auth fields to websites table
    op.add_column('websites', sa.Column('requires_auth', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('websites', sa.Column('auth_username', sa.String(), nullable=True))
    op.add_column('websites', sa.Column('encrypted_auth_password', sa.String(), nullable=True))
    op.add_column('websites', sa.Column('auth_last_verified', sa.TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    # Remove basic auth fields from websites table
    op.drop_column('websites', 'auth_last_verified')
    op.drop_column('websites', 'encrypted_auth_password')
    op.drop_column('websites', 'auth_username')
    op.drop_column('websites', 'requires_auth')