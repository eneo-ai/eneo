"""Eneo's OAuth client state toward one MCP server.

A connection is the tokens Eneo holds for one principal at one server: a user
(``user_id`` set) or the server's shared identity (``user_id`` None). Tokens
are plaintext on the entity; the repository encrypts them at rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional
from uuid import UUID

ConnectionStrategy = Literal["auth_code", "id_jag", "client_credentials"]
ConnectionStatus = Literal["connected", "needs_authorization"]

STRATEGY_AUTH_CODE: ConnectionStrategy = "auth_code"
STRATEGY_ID_JAG: ConnectionStrategy = "id_jag"
STRATEGY_CLIENT_CREDENTIALS: ConnectionStrategy = "client_credentials"

STATUS_CONNECTED: ConnectionStatus = "connected"
STATUS_NEEDS_AUTHORIZATION: ConnectionStatus = "needs_authorization"

# A token this close to expiry is refreshed before use, so a tool call never
# starts with a token that dies mid-request.
TOKEN_EXPIRY_LEEWAY = timedelta(seconds=60)


@dataclass
class MCPOAuthConnection:
    tenant_id: UUID
    mcp_server_id: UUID
    user_id: Optional[UUID]
    issuer: str
    resource: str
    strategy: ConnectionStrategy
    status: ConnectionStatus = STATUS_CONNECTED
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    scopes: list[str] = field(default_factory=lambda: list[str]())
    last_error: Optional[str] = None
    connected_by_user_id: Optional[UUID] = None
    id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def is_shared(self) -> bool:
        return self.user_id is None

    @property
    def is_connected(self) -> bool:
        return self.status == STATUS_CONNECTED and bool(self.access_token)

    def token_is_fresh(self, now: Optional[datetime] = None) -> bool:
        """True when the access token can be sent as is."""
        if not self.access_token or self.status != STATUS_CONNECTED:
            return False
        if self.expires_at is None:
            return True
        now = now or datetime.now(timezone.utc)
        return self.expires_at - TOKEN_EXPIRY_LEEWAY > now

    def invalidate(self, reason: str) -> None:
        """The server or authorization server refused the stored tokens."""
        self.status = STATUS_NEEDS_AUTHORIZATION
        self.access_token = None
        self.refresh_token = None
        self.expires_at = None
        self.last_error = reason

    def accept_tokens(
        self,
        *,
        access_token: str,
        refresh_token: Optional[str],
        expires_at: Optional[datetime],
        scopes: Optional[list[str]] = None,
    ) -> None:
        self.access_token = access_token
        # A token response without a refresh token keeps the one we have,
        # unless the authorization server rotated it (then it is new here).
        if refresh_token:
            self.refresh_token = refresh_token
        self.expires_at = expires_at
        if scopes is not None:
            self.scopes = scopes
        self.status = STATUS_CONNECTED
        self.last_error = None


@dataclass
class MCPOAuthClientRegistration:
    """Eneo's client identity at one authorization server."""

    tenant_id: UUID
    mcp_server_id: UUID
    issuer: str
    client_id: str
    client_secret: Optional[str]
    source: Literal["pre_registered", "dcr"]
    registration_payload: Optional[dict[str, Any]] = None
    id: Optional[UUID] = None


@dataclass
class IdpUserToken:
    """The ID token a user received at login, kept for ID-JAG exchanges."""

    user_id: UUID
    tenant_id: UUID
    idp_issuer: str
    idp_subject: Optional[str]
    id_token: str
    id_token_expires_at: Optional[datetime] = None
    id: Optional[UUID] = None
