# flake8: noqa

"""add mcp servers tables

Revision ID: add_mcp_servers
Revises: 3914e3c83f18
Create Date: 2025-10-27 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

# revision identifiers, used by Alembic
revision = 'add_mcp_servers'
down_revision = '3914e3c83f18'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create MCP servers tables and relationships."""

    # Create mcp_servers table (global catalog)
    op.create_table(
        'mcp_servers',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('server_type', sa.String(), nullable=False),
        sa.Column('npm_package', sa.String(), nullable=True),
        sa.Column('docker_image', sa.String(), nullable=True),
        sa.Column('http_url', sa.String(), nullable=True),
        sa.Column('config_schema', JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('tags', JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('icon_url', sa.String(), nullable=True),
        sa.Column('documentation_url', sa.String(), nullable=True),
    )

    # Create mcp_server_settings table (tenant-level enablement)
    op.create_table(
        'mcp_server_settings',
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('mcp_server_id', UUID(as_uuid=True), sa.ForeignKey('mcp_servers.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('is_org_enabled', sa.Boolean(), server_default='False', nullable=False),
        sa.Column('env_vars', JSONB(astext_type=sa.Text()), nullable=True),
    )

    # Create assistant_mcp_servers table (assistant many-to-many)
    op.create_table(
        'assistant_mcp_servers',
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column('assistant_id', UUID(as_uuid=True), sa.ForeignKey('assistants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('mcp_server_id', UUID(as_uuid=True), sa.ForeignKey('mcp_servers.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('enabled', sa.Boolean(), server_default='True', nullable=False),
        sa.Column('config', JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('priority', sa.Integer(), server_default='0', nullable=False),
    )

    # Seed context7 MCP server
    op.execute("""
        INSERT INTO mcp_servers (name, description, server_type, npm_package, tags, documentation_url)
        VALUES (
            'Context7',
            'Up-to-date documentation for popular libraries and frameworks',
            'npm',
            '@upstash/context7-mcp',
            '["documentation", "libraries", "frameworks"]',
            'https://github.com/upstash/context7-mcp'
        )
    """)


def downgrade() -> None:
    """Drop MCP servers tables."""
    op.drop_table('assistant_mcp_servers')
    op.drop_table('mcp_server_settings')
    op.drop_table('mcp_servers')
