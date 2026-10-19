"""Tables for Eneo acting as an OAuth 2.1 client toward MCP servers.

An MCP server with ``http_auth_type = "oauth"`` is protected by the vendor's
own authorization server. Eneo obtains tokens for it either per user (each
user authorizes once in a browser popup, or silently through the
Enterprise-Managed Authorization extension) or once per server (a shared
machine or service-account identity chosen by the tenant admin).

``mcp_oauth_connections`` holds the tokens: one row per user and server, or
one row with ``user_id IS NULL`` for a shared connection. Tokens are stored
as Fernet envelopes and never leave the backend.

``mcp_oauth_client_registrations`` remembers the client identity Eneo uses at
one authorization server (an admin-entered pre-registration or a Dynamic
Client Registration result), bound to that server's ``issuer`` as the spec
requires.

``idp_user_tokens`` keeps the ID token a user received at login, which is the
identity assertion the ID-JAG strategy exchanges at the IdP. It is written
only for tenants whose federation config enables that strategy.

``mcp_oauth_signing_keys`` holds the deployment's keys for ``private_key_jwt``
client authentication: the private key as a Fernet envelope, the public key
as the JWK the backend publishes.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import (
    TIMESTAMP,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.mcp_server_table import MCPServers
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users


class MCPOAuthConnections(BasePublic):
    __tablename__ = "mcp_oauth_connections"  # type: ignore[assignment]
    __table_args__ = (
        # One connection per user and server; NULL user ids never collide in a
        # unique constraint, so the shared row has its own partial index.
        UniqueConstraint(
            "mcp_server_id", "user_id", name="uq_mcp_oauth_connections_server_user"
        ),
        Index(
            "uq_mcp_oauth_connections_shared",
            "mcp_server_id",
            unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
        Index("ix_mcp_oauth_connections_user_id", "user_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False
    )
    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServers.id, ondelete="CASCADE"), nullable=False
    )
    # NULL marks the server's shared connection.
    user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), nullable=True
    )
    # The authorization server that issued the tokens and the MCP resource
    # they are bound to (RFC 8707).
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    # auth_code | id_jag | client_credentials
    strategy: Mapped[str] = mapped_column(String, nullable=False)
    # connected | needs_authorization
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="connected"
    )
    access_token_ciphertext: Mapped[Optional[str]] = mapped_column(Text)
    refresh_token_ciphertext: Mapped[Optional[str]] = mapped_column(Text)
    expires_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    scopes: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    connected_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"), nullable=True
    )


class MCPOAuthClientRegistrations(BasePublic):
    __tablename__ = "mcp_oauth_client_registrations"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint(
            "mcp_server_id",
            "issuer",
            name="uq_mcp_oauth_client_registrations_server_issuer",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False
    )
    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey(MCPServers.id, ondelete="CASCADE"), nullable=False
    )
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_secret_ciphertext: Mapped[Optional[str]] = mapped_column(Text)
    # pre_registered | dcr
    source: Mapped[str] = mapped_column(String, nullable=False)
    registration_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)


class IdpUserTokens(BasePublic):
    __tablename__ = "idp_user_tokens"  # type: ignore[assignment]
    __table_args__ = (UniqueConstraint("user_id", name="uq_idp_user_tokens_user"),)

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False
    )
    idp_issuer: Mapped[str] = mapped_column(Text, nullable=False)
    idp_subject: Mapped[Optional[str]] = mapped_column(Text)
    id_token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    id_token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )


class MCPOAuthSigningKeys(BasePublic):
    __tablename__ = "mcp_oauth_signing_keys"  # type: ignore[assignment]
    __table_args__ = (UniqueConstraint("kid", name="uq_mcp_oauth_signing_keys_kid"),)

    kid: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm: Mapped[str] = mapped_column(String, nullable=False)
    private_key_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    public_jwk: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    retired_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
