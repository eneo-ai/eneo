"""simplify_mcp_schema_tenant_only

Revision ID: 15e39b6c6245
Revises: 20251030_153511
Create Date: 2025-10-31 14:04:28.286744

Simplify MCP schema to tenant-only:
- Merge mcp_server_settings into mcp_servers
- Remove mcp_server_tool_settings (tenant-level tool overrides not needed)
- MCP servers are now per-tenant, not global
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic
revision = '15e39b6c6245'
down_revision = '20251030_153511'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Simplify MCP schema to be tenant-only."""

    # Step 1: Delete existing data (breaking change)
    op.execute("DELETE FROM mcp_server_settings")
    op.execute("DELETE FROM mcp_server_tool_settings")
    op.execute("DELETE FROM assistant_mcp_servers")
    op.execute("DELETE FROM spaces_mcp_server_tools")
    op.execute("DELETE FROM spaces_mcp_servers")
    op.execute("DELETE FROM mcp_server_tools")
    op.execute("DELETE FROM mcp_servers")

    # Step 2: Add tenant columns to mcp_servers
    op.add_column('mcp_servers', sa.Column('tenant_id', UUID(as_uuid=True), nullable=True))
    op.add_column('mcp_servers', sa.Column('is_enabled', sa.Boolean(), server_default='True', nullable=False))
    op.add_column('mcp_servers', sa.Column('env_vars', JSONB(astext_type=sa.Text()), nullable=True))

    # Step 3: Create foreign key for tenant_id
    op.create_foreign_key(
        'fk_mcp_servers_tenant_id',
        'mcp_servers', 'tenants',
        ['tenant_id'], ['id'],
        ondelete='CASCADE'
    )

    # Step 4: Make tenant_id NOT NULL (after adding FK)
    op.alter_column('mcp_servers', 'tenant_id', nullable=False)

    # Step 5: Add unique constraint (tenant_id, name)
    op.create_unique_constraint(
        'uq_mcp_servers_tenant_name',
        'mcp_servers',
        ['tenant_id', 'name']
    )

    # Step 6: Keep mcp_server_tool_settings for tenant-level tool overrides
    # (Only drop mcp_server_settings, which was merged into mcp_servers)
    op.drop_table('mcp_server_settings')


def downgrade() -> None:
    """Revert to separate settings tables."""

    # Recreate mcp_server_settings table
    op.create_table(
        'mcp_server_settings',
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('mcp_server_id', UUID(as_uuid=True), sa.ForeignKey('mcp_servers.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('is_org_enabled', sa.Boolean(), server_default='False', nullable=False),
        sa.Column('env_vars', JSONB(astext_type=sa.Text()), nullable=True),
    )

    # Recreate mcp_server_tool_settings table
    op.create_table(
        'mcp_server_tool_settings',
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('mcp_server_tool_id', UUID(as_uuid=True), sa.ForeignKey('mcp_server_tools.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('is_enabled', sa.Boolean(), server_default='True', nullable=False),
    )

    # Drop unique constraint
    op.drop_constraint('uq_mcp_servers_tenant_name', 'mcp_servers', type_='unique')

    # Drop foreign key
    op.drop_constraint('fk_mcp_servers_tenant_id', 'mcp_servers', type_='foreignkey')

    # Remove columns from mcp_servers
    op.drop_column('mcp_servers', 'env_vars')
    op.drop_column('mcp_servers', 'is_enabled')
    op.drop_column('mcp_servers', 'tenant_id')