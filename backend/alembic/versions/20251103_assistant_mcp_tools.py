"""assistant_mcp_tools

Revision ID: 20251103_assistant_mcp
Revises: 15e39b6c6245
Create Date: 2025-11-03

Add assistant-level MCP tool permissions table and simplify assistant_mcp_servers:
- Create assistant_mcp_server_tools table for tool-level overrides
- Remove columns from assistant_mcp_servers (enabled, config, priority, tool_overrides)
- Assistant MCP management now matches the space pattern
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic
revision = '20251103_assistant_mcp'
down_revision = '15e39b6c6245'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add assistant MCP tools table and simplify assistant_mcp_servers."""

    # Step 1: Delete existing data (breaking change)
    op.execute("DELETE FROM assistant_mcp_servers")

    # Step 2: Create assistant_mcp_server_tools table
    op.create_table(
        'assistant_mcp_server_tools',
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('assistant_id', UUID(as_uuid=True), sa.ForeignKey('assistants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('mcp_server_tool_id', UUID(as_uuid=True), sa.ForeignKey('mcp_server_tools.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('is_enabled', sa.Boolean(), server_default='True', nullable=False),
    )

    # Step 3: Drop old columns from assistant_mcp_servers
    op.drop_column('assistant_mcp_servers', 'enabled')
    op.drop_column('assistant_mcp_servers', 'config')
    op.drop_column('assistant_mcp_servers', 'priority')
    op.drop_column('assistant_mcp_servers', 'tool_overrides')


def downgrade() -> None:
    """Revert to old assistant_mcp_servers schema."""

    # Drop new table
    op.drop_table('assistant_mcp_server_tools')

    # Re-add old columns to assistant_mcp_servers
    op.add_column('assistant_mcp_servers', sa.Column('enabled', sa.Boolean(), server_default='True'))
    op.add_column('assistant_mcp_servers', sa.Column('config', JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('assistant_mcp_servers', sa.Column('priority', sa.Integer(), server_default='0'))
    op.add_column('assistant_mcp_servers', sa.Column('tool_overrides', JSONB(astext_type=sa.Text()), nullable=True))
