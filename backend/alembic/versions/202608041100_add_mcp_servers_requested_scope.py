"""mcp_servers: requested_scope column

Adds ``requested_scope``, a space-separated list of OAuth scopes requested
during token exchange. Overrides the PRM ``scopes_supported`` derivation;
needed when the resource does not advertise scopes but its API enforces
them.

Nullable: most servers rely on PRM-derived scopes, so this is opt-in per
server.

Revision ID: 202608041100
Revises: 202608041000
Create Date: 2026-08-04
"""

import sqlalchemy as sa

from alembic import op

revision = "202608041100"
down_revision = "202608041000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column("requested_scope", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "requested_scope")
