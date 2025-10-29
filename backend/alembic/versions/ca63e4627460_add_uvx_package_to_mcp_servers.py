"""add_uvx_package_to_mcp_servers
Revision ID: ca63e4627460
Revises: add_mcp_servers
Create Date: 2025-10-28 12:50:41.356658
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = 'ca63e4627460'
down_revision = 'add_mcp_servers'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('mcp_servers', sa.Column('uvx_package', sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column('mcp_servers', 'uvx_package')