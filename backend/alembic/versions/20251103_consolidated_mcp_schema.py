"""consolidated MCP schema

Revision ID: 20251103_consolidated_mcp
Revises: 3914e3c83f18
Create Date: 2025-11-03 00:00:00.000000

This migration consolidates 5 separate MCP migrations into a single clean migration:
- 20251027_add_mcp_servers
- ca63e4627460_add_uvx_package_to_mcp_servers
- 20251030_153511_refactor_mcp_http_only
- 15e39b6c6245_simplify_mcp_schema_tenant_only
- 20251103_assistant_mcp_tools

Final schema (7 tables):
- mcp_servers: Tenant-level MCP servers with HTTP transport only
- mcp_server_tools: Tool catalog per server
- mcp_server_tool_settings: Tenant-level tool permissions
- spaces_mcp_servers: Space-level server selection
- spaces_mcp_server_tools: Space-level tool permissions
- assistant_mcp_servers: Assistant-level server selection
- assistant_mcp_server_tools: Assistant-level tool permissions

Hierarchical permissions: Tenant -> Space -> Assistant
Tool-level overrides at tenant, space, and assistant levels
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

# revision identifiers, used by Alembic
revision = '20251103_consolidated_mcp'
down_revision = '3914e3c83f18'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create complete MCP schema in final form."""

    # Table 1: mcp_servers (tenant-level MCP servers)
    op.create_table(
        'mcp_servers',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('http_url', sa.String(), nullable=False),
        sa.Column('transport_type', sa.String(), nullable=False, server_default='sse'),
        sa.Column('http_auth_type', sa.String(), nullable=False, server_default='none'),
        sa.Column('http_auth_config_schema', JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), server_default='True', nullable=False),
        sa.Column('env_vars', JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('tags', JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('icon_url', sa.String(), nullable=True),
        sa.Column('documentation_url', sa.String(), nullable=True),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_mcp_servers_tenant_name'),
    )

    # Table 2: mcp_server_tools (tool catalog per server)
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
        sa.UniqueConstraint('mcp_server_id', 'name', name='uq_mcp_server_tools_server_name'),
    )

    # Table 3: mcp_server_tool_settings (tenant-level tool permissions)
    op.create_table(
        'mcp_server_tool_settings',
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('mcp_server_tool_id', UUID(as_uuid=True), sa.ForeignKey('mcp_server_tools.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('is_enabled', sa.Boolean(), server_default='True', nullable=False),
    )

    # Table 4: spaces_mcp_servers (space-level server selection)
    op.create_table(
        'spaces_mcp_servers',
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('space_id', UUID(as_uuid=True), sa.ForeignKey('spaces.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('mcp_server_id', UUID(as_uuid=True), sa.ForeignKey('mcp_servers.id', ondelete='CASCADE'), primary_key=True),
    )

    # Table 5: spaces_mcp_server_tools (space-level tool permissions)
    op.create_table(
        'spaces_mcp_server_tools',
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('space_id', UUID(as_uuid=True), sa.ForeignKey('spaces.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('mcp_server_tool_id', UUID(as_uuid=True), sa.ForeignKey('mcp_server_tools.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('is_enabled', sa.Boolean(), server_default='True', nullable=False),
    )

    # Table 6: assistant_mcp_servers (assistant-level server selection)
    op.create_table(
        'assistant_mcp_servers',
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('assistant_id', UUID(as_uuid=True), sa.ForeignKey('assistants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('mcp_server_id', UUID(as_uuid=True), sa.ForeignKey('mcp_servers.id', ondelete='CASCADE'), primary_key=True),
    )

    # Table 7: assistant_mcp_server_tools (assistant-level tool permissions)
    op.create_table(
        'assistant_mcp_server_tools',
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('assistant_id', UUID(as_uuid=True), sa.ForeignKey('assistants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('mcp_server_tool_id', UUID(as_uuid=True), sa.ForeignKey('mcp_server_tools.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('is_enabled', sa.Boolean(), server_default='True', nullable=False),
    )


def downgrade() -> None:
    """Drop all MCP tables."""
    op.drop_table('assistant_mcp_server_tools')
    op.drop_table('assistant_mcp_servers')
    op.drop_table('spaces_mcp_server_tools')
    op.drop_table('spaces_mcp_servers')
    op.drop_table('mcp_server_tool_settings')
    op.drop_table('mcp_server_tools')
    op.drop_table('mcp_servers')
