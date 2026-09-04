"""Built-in capability providers

A built-in provider is an mcp_servers row whose endpoint is one of Eneo's own
loopback MCP servers (http_auth_type = "internal"). ``provider_config`` holds
which tenant model provider and model the loopback tool calls; it is present
exactly for those rows.

Revision ID: 202607101007
Revises: 202607101006
Create Date: 2026-09-04

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "202607101007"
down_revision = "202607101006"
branch_labels = None
depends_on = None

CONSTRAINT = "ck_mcp_servers_internal_provider_config"


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column(
            "provider_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.create_check_constraint(
        CONSTRAINT,
        "mcp_servers",
        "(http_auth_type = 'internal') = (provider_config IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "mcp_servers", type_="check")
    op.drop_column("mcp_servers", "provider_config")
