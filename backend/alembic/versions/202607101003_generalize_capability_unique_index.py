"""Generalize the single-active-provider constraint to every capability purpose

mcp_servers.purpose now covers more than web search ("image_generation" joins
"web_search"). The partial unique index that guaranteed at most one enabled
web-search server per tenant becomes one active provider per tenant AND
capability purpose; general-purpose servers stay unconstrained.

Revision ID: 202607101003
Revises: 202607101002
Create Date: 2026-09-03

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "202607101003"
down_revision = "202607101002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "uq_mcp_servers_tenant_active_web_search",
        table_name="mcp_servers",
    )
    op.create_index(
        "uq_mcp_servers_tenant_active_capability",
        "mcp_servers",
        ["tenant_id", "purpose"],
        unique=True,
        postgresql_where=sa.text("purpose <> 'general' AND is_enabled = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_mcp_servers_tenant_active_capability",
        table_name="mcp_servers",
    )
    op.create_index(
        "uq_mcp_servers_tenant_active_web_search",
        "mcp_servers",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("purpose = 'web_search' AND is_enabled = true"),
    )
