"""mcp_servers: OAuth token-exchange columns

Adds the per-server configuration for the MCP token broker:

- ``auth_scope`` selects between the existing static-bearer flow and the
  broker-driven flows. All existing rows backfill to ``static_bearer`` so
  behavior is unchanged until an operator opts a server into ``per_user``
  or ``per_tenant`` (gated by ``MCP_OAUTH_ENABLED`` at the API layer).
- ``expected_idp_issuer`` is the issuer assertion gate: when set, the
  broker requires the server's published authorization server to match.
- ``tool_discovery_principal`` is the identity used to populate the tool
  catalog. The catalog describes the server's surface, not what a given
  user can do, so it is decoupled from ``auth_scope``.
- ``target_resource_or_scope`` is the strategy-target hint (the RFC 8707
  ``resource`` / RFC 8693 ``audience`` value).
- ``exchange_protocol`` picks the token-exchange strategy. ``auto``
  resolves via authorization-server metadata discovery: servers whose AS
  advertises the ``id-jag`` grant profile use the two-step Identity
  Assertion Authorization Grant flow, everything else falls back to the
  single-step same-IdP RFC 8693 exchange. Explicit values pin a strategy
  for IdPs with broken or absent metadata.

Revision ID: 202608031000
Revises: 202607301200
Create Date: 2026-08-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202608031000"
down_revision = "202607301200"
branch_labels = None
depends_on = None

AUTH_SCOPE_VALUES = ("per_user", "per_tenant", "static_bearer")
AUTH_SCOPE_ENUM_NAME = "mcp_auth_scope"

DISCOVERY_PRINCIPAL_VALUES = ("anonymous", "tenant_service_account", "admin_user")
DISCOVERY_PRINCIPAL_ENUM_NAME = "mcp_discovery_principal"

EXCHANGE_PROTOCOL_VALUES = ("auto", "id_jag", "rfc8693")
EXCHANGE_PROTOCOL_ENUM_NAME = "mcp_exchange_protocol"


def upgrade() -> None:
    bind = op.get_bind()

    auth_scope_enum = postgresql.ENUM(
        *AUTH_SCOPE_VALUES, name=AUTH_SCOPE_ENUM_NAME, create_type=False
    )
    auth_scope_enum.create(bind, checkfirst=True)

    discovery_enum = postgresql.ENUM(
        *DISCOVERY_PRINCIPAL_VALUES,
        name=DISCOVERY_PRINCIPAL_ENUM_NAME,
        create_type=False,
    )
    discovery_enum.create(bind, checkfirst=True)

    exchange_protocol_enum = postgresql.ENUM(
        *EXCHANGE_PROTOCOL_VALUES,
        name=EXCHANGE_PROTOCOL_ENUM_NAME,
        create_type=False,
    )
    exchange_protocol_enum.create(bind, checkfirst=True)

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
    op.add_column(
        "mcp_servers",
        sa.Column(
            "tool_discovery_principal",
            discovery_enum,
            nullable=False,
            server_default="anonymous",
        ),
    )
    op.add_column(
        "mcp_servers",
        sa.Column("target_resource_or_scope", sa.Text(), nullable=True),
    )
    op.add_column(
        "mcp_servers",
        sa.Column(
            "exchange_protocol",
            exchange_protocol_enum,
            nullable=False,
            server_default="auto",
        ),
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "exchange_protocol")
    op.drop_column("mcp_servers", "target_resource_or_scope")
    op.drop_column("mcp_servers", "tool_discovery_principal")
    op.drop_column("mcp_servers", "expected_idp_issuer")
    op.drop_column("mcp_servers", "auth_scope")

    bind = op.get_bind()
    postgresql.ENUM(
        *EXCHANGE_PROTOCOL_VALUES,
        name=EXCHANGE_PROTOCOL_ENUM_NAME,
        create_type=False,
    ).drop(bind, checkfirst=True)
    postgresql.ENUM(
        *DISCOVERY_PRINCIPAL_VALUES,
        name=DISCOVERY_PRINCIPAL_ENUM_NAME,
        create_type=False,
    ).drop(bind, checkfirst=True)
    postgresql.ENUM(
        *AUTH_SCOPE_VALUES,
        name=AUTH_SCOPE_ENUM_NAME,
        create_type=False,
    ).drop(bind, checkfirst=True)
