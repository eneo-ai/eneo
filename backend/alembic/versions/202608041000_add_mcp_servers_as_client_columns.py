"""mcp_servers: authorization-server client columns

Adds the OAuth client registered at an MCP server's authorization server,
used for the ID-JAG leg-2 jwt-bearer redemption when that AS requires
client authentication. Distinct from the federation client at the IdP.

- ``as_client_id`` is the client_id, stored in plaintext (not a secret).
- ``as_client_secret`` holds a Fernet envelope (``enc:fernet:v1:...``),
  never plaintext.

Both columns are nullable: most authorization servers used with id_jag
do not require client authentication on the redemption request, so this
is opt-in per server.

Revision ID: 202608041000
Revises: 202608031200
Create Date: 2026-08-04
"""

import sqlalchemy as sa

from alembic import op

revision = "202608041000"
down_revision = "202608031200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column("as_client_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "mcp_servers",
        sa.Column("as_client_secret", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "as_client_secret")
    op.drop_column("mcp_servers", "as_client_id")
