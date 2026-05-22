"""mcp_servers: auth_scope enum + expected_idp_issuer

Phase 1 of the same-IdP MCP OAuth work. Adds the discriminator that selects
between the existing static-bearer flow and the upcoming token-exchange
flows (RFC 8693 for Keycloak, On-Behalf-Of for Entra). All existing rows
backfill to ``static_bearer`` so server behavior is unchanged until an
operator explicitly opts in by setting ``per_user`` or ``per_tenant``
on a server (gated by ``MCP_OAUTH_ENABLED`` at the API layer).

``expected_idp_issuer`` is the "same-IdP" assertion gate. When set, the
broker (lands in Phase 3) requires the user's logged-in IdP issuer and
the MCP server's published authorization-server issuer to both equal
this value. Nullable here so existing rows do not need a value.

Revision ID: 202605221000
Revises: 202605201000
Create Date: 2026-05-22
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202605221000"
down_revision = "202605201000"
branch_labels = None
depends_on = None

AUTH_SCOPE_VALUES = ("per_user", "per_tenant", "static_bearer")
AUTH_SCOPE_ENUM_NAME = "mcp_auth_scope"


def upgrade() -> None:
    auth_scope_enum = postgresql.ENUM(
        *AUTH_SCOPE_VALUES, name=AUTH_SCOPE_ENUM_NAME, create_type=False
    )
    auth_scope_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "mcp_servers",
        sa.Column(
            "auth_scope",
            auth_scope_enum,
            nullable=False,
            server_default="static_bearer",
        ),
    )
    op.add_column(
        "mcp_servers",
        sa.Column("expected_idp_issuer", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "expected_idp_issuer")
    op.drop_column("mcp_servers", "auth_scope")

    auth_scope_enum = postgresql.ENUM(
        *AUTH_SCOPE_VALUES, name=AUTH_SCOPE_ENUM_NAME, create_type=False
    )
    auth_scope_enum.drop(op.get_bind(), checkfirst=True)
