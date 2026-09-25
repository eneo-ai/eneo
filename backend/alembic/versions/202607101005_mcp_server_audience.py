"""Capability provider audiences

A capability provider (web search, image generation) serves either everyone in
the tenant (the default provider) or the members of selected user groups.
Group-targeted providers coexist with the default, so the single-active-
provider index now guards only the default provider per tenant and purpose.

Revision ID: 202607101005
Revises: 202607101004
Create Date: 2026-09-03

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "202607101005"
down_revision = "202607101004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column("audience", sa.String(), nullable=False, server_default="everyone"),
    )
    op.add_column(
        "mcp_servers",
        sa.Column(
            "audience_priority", sa.Integer(), nullable=False, server_default="100"
        ),
    )
    op.create_table(
        "mcp_server_user_groups",
        sa.Column("mcp_server_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["mcp_server_id"], ["mcp_servers.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_group_id"], ["user_groups.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("mcp_server_id", "user_group_id"),
    )
    op.drop_index("uq_mcp_servers_tenant_active_capability", table_name="mcp_servers")
    op.create_index(
        "uq_mcp_servers_tenant_active_capability",
        "mcp_servers",
        ["tenant_id", "purpose"],
        unique=True,
        postgresql_where=sa.text(
            "purpose <> 'general' AND is_enabled = true AND audience = 'everyone'"
        ),
    )


def downgrade() -> None:
    # Group-targeted providers cannot exist under the stricter index; keep only
    # the default provider active per purpose.
    op.execute(
        """
        UPDATE mcp_servers
        SET is_enabled = false
        WHERE purpose <> 'general' AND audience <> 'everyone';
        """
    )
    op.drop_index("uq_mcp_servers_tenant_active_capability", table_name="mcp_servers")
    op.create_index(
        "uq_mcp_servers_tenant_active_capability",
        "mcp_servers",
        ["tenant_id", "purpose"],
        unique=True,
        postgresql_where=sa.text("purpose <> 'general' AND is_enabled = true"),
    )
    op.drop_table("mcp_server_user_groups")
    op.drop_column("mcp_servers", "audience_priority")
    op.drop_column("mcp_servers", "audience")
