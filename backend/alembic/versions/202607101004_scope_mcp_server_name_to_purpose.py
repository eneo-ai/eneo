"""Scope MCP server name uniqueness to purpose

One vendor may provide several capabilities from different endpoints (a
web-search server and an image-generation server both called "GDM"). Names
stay unique within a tenant and purpose instead of across the whole catalog.

Revision ID: 202607101004
Revises: 202607101003
Create Date: 2026-09-03

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "202607101004"
down_revision = "202607101003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_mcp_servers_tenant_name", "mcp_servers", type_="unique")
    op.create_unique_constraint(
        "uq_mcp_servers_tenant_name_purpose",
        "mcp_servers",
        ["tenant_id", "name", "purpose"],
    )


def downgrade() -> None:
    # Fails if a tenant reuses a name across purposes; rename before downgrading.
    op.drop_constraint(
        "uq_mcp_servers_tenant_name_purpose", "mcp_servers", type_="unique"
    )
    op.create_unique_constraint(
        "uq_mcp_servers_tenant_name", "mcp_servers", ["tenant_id", "name"]
    )
