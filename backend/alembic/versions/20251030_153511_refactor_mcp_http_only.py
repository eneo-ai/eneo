"""refactor MCP to HTTP-only with tool-level permissions

Revision ID: 20251030_153511
Revises: ca63e4627460
Create Date: 2025-10-30 15:35:11.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

# revision identifiers, used by Alembic
revision = '20251030_153511'
down_revision = 'ca63e4627460'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Refactor MCP servers to HTTP-only and add tool-level permissions."""

    # Step 1: Delete existing MCP server data (breaking change)
    op.execute("DELETE FROM assistant_mcp_servers")
    op.execute("DELETE FROM mcp_server_settings")
    op.execute("DELETE FROM mcp_servers")

    # Step 2: Drop stdio-related columns from mcp_servers
    op.drop_column('mcp_servers', 'server_type')
    op.drop_column('mcp_servers', 'npm_package')
    op.drop_column('mcp_servers', 'uvx_package')
    op.drop_column('mcp_servers', 'docker_image')

    # Step 3: Add HTTP configuration columns to mcp_servers (using String, not ENUM)
    op.add_column('mcp_servers', sa.Column('transport_type', sa.String(), nullable=False, server_default='sse'))
    op.add_column('mcp_servers', sa.Column('http_auth_type', sa.String(), nullable=False, server_default='none'))
    op.add_column('mcp_servers', sa.Column('http_auth_config_schema', JSONB(astext_type=sa.Text()), nullable=True))

    # Make http_url required (not nullable)
    op.alter_column('mcp_servers', 'http_url', nullable=False)

    # Step 4: Create mcp_server_tools table (tool catalog)
    op.create_table(
        'mcp_server_tools',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('mcp_server_id', UUID(as_uuid=True), sa.ForeignKey('mcp_servers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('input_schema', JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_enabled_by_default', sa.Boolean(), server_default='True', nullable=False),
        # Ensure unique tool names per server
        sa.UniqueConstraint('mcp_server_id', 'name', name='uq_mcp_server_tools_server_name'),
    )

    # Step 5: Create mcp_server_tool_settings table (tenant-level tool permissions)
    op.create_table(
        'mcp_server_tool_settings',
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('mcp_server_tool_id', UUID(as_uuid=True), sa.ForeignKey('mcp_server_tools.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('is_enabled', sa.Boolean(), server_default='True', nullable=False),
    )

    # Step 6: Create spaces_mcp_servers table (space-level server selection)
    op.create_table(
        'spaces_mcp_servers',
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('space_id', UUID(as_uuid=True), sa.ForeignKey('spaces.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('mcp_server_id', UUID(as_uuid=True), sa.ForeignKey('mcp_servers.id', ondelete='CASCADE'), primary_key=True),
    )

    # Step 7: Create spaces_mcp_server_tools table (space-level tool permissions)
    op.create_table(
        'spaces_mcp_server_tools',
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('space_id', UUID(as_uuid=True), sa.ForeignKey('spaces.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('mcp_server_tool_id', UUID(as_uuid=True), sa.ForeignKey('mcp_server_tools.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('is_enabled', sa.Boolean(), server_default='True', nullable=False),
    )

    # Step 8: Update assistant_mcp_servers table to add tool_overrides
    op.add_column('assistant_mcp_servers', sa.Column('tool_overrides', JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Revert to stdio-based MCP servers."""

    # Drop new tables
    op.drop_table('spaces_mcp_server_tools')
    op.drop_table('spaces_mcp_servers')
    op.drop_table('mcp_server_tool_settings')
    op.drop_table('mcp_server_tools')

    # Remove tool_overrides from assistant_mcp_servers
    op.drop_column('assistant_mcp_servers', 'tool_overrides')

    # Revert mcp_servers table
    op.alter_column('mcp_servers', 'http_url', nullable=True)
    op.drop_column('mcp_servers', 'http_auth_config_schema')
    op.drop_column('mcp_servers', 'http_auth_type')
    op.drop_column('mcp_servers', 'transport_type')

    # Re-add stdio columns
    op.add_column('mcp_servers', sa.Column('server_type', sa.String(), nullable=True))
    op.add_column('mcp_servers', sa.Column('npm_package', sa.String(), nullable=True))
    op.add_column('mcp_servers', sa.Column('uvx_package', sa.String(), nullable=True))
    op.add_column('mcp_servers', sa.Column('docker_image', sa.String(), nullable=True))
