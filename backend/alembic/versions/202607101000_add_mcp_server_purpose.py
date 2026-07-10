"""Add purpose to mcp_servers with single-active web-search constraint

Adds the purpose discriminator ("general" | "web_search") to the MCP server
catalog. Existing rows default to "general" and are unaffected. A partial
unique index guarantees at most one enabled web-search server per tenant;
activation switches providers transactionally under that constraint.

Revision ID: 202607101000
Revises: 202607071000
Create Date: 2026-07-10

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "202607101000"
down_revision = "202607071000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column("purpose", sa.String(), nullable=False, server_default="general"),
    )
    op.create_index(
        "uq_mcp_servers_tenant_active_web_search",
        "mcp_servers",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("purpose = 'web_search' AND is_enabled = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_mcp_servers_tenant_active_web_search",
        table_name="mcp_servers",
    )
    op.drop_column("mcp_servers", "purpose")
