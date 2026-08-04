"""mcp_servers: as_issuer column

Adds ``as_issuer``, which pins the authorization-server issuer that the
per-server AS client credentials (``as_client_id`` / ``as_client_secret``)
may be sent to during ID-JAG leg-2 redemption. Without this pin, a
compromised MCP server could steer leg 2 to an attacker-controlled
authorization server via its protected-resource metadata and harvest the
reusable client secret.

Nullable: servers that do not have per-server AS credentials configured
do not need an issuer pin.

Revision ID: 202608041200
Revises: 202608041100
Create Date: 2026-08-04
"""

import sqlalchemy as sa

from alembic import op

revision = "202608041200"
down_revision = "202608041100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column("as_issuer", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "as_issuer")
