"""Per-user MCP connection status.

For each MCP server the current user can see, reports whether the token
broker is in a state where it can mint a usable bearer for that server.
The chat UI surfaces this to explain "tool X is unavailable because you
haven't authenticated to its provider" without leaking implementation
detail.

Status vocabulary:

- ``connected``: the broker can serve this server for the caller, either
  from a fresh cached exchanged token or because the user's SSO session
  matches the expected IdP (the broker mints on first use).
- ``expired``: cached token exists but has aged past ``expires_at``. The
  next tool call re-exchanges automatically; shown so users understand a
  brief delay.
- ``not_authenticated``: the user has no stored IdP token at all; a
  fresh SSO login fixes it.
- ``idp_mismatch``: the user logged in via a different IdP than the
  server expects (or the server is missing its issuer config). No user
  action can fix this; an operator must update the configuration.
- ``not_applicable``: no per-user state drives this server
  (``static_bearer``, or ``per_tenant`` before the first tenant
  exchange).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal, Optional
from uuid import UUID

if TYPE_CHECKING:
    from eneo.mcp_servers.application.mcp_server_settings_service import (
        MCPServerSettingsService,
    )
    from eneo.mcp_servers.domain.repositories.mcp_connection_repo import (
        MCPConnectionRepository,
    )
    from eneo.users.user import UserInDB

MCPConnectionStatusValue = Literal[
    "connected",
    "expired",
    "not_authenticated",
    "idp_mismatch",
    "not_applicable",
]


@dataclass(frozen=True)
class MCPConnectionState:
    mcp_server_id: UUID
    name: str
    auth_scope: str
    expected_idp_issuer: Optional[str]
    status: MCPConnectionStatusValue
    expires_at: Optional[datetime]


class MCPConnectionService:
    def __init__(
        self,
        *,
        connection_repo: "MCPConnectionRepository",
        mcp_server_settings_service: "MCPServerSettingsService",
        user: "UserInDB",
    ):
        self._connection_repo = connection_repo
        self._settings_service = mcp_server_settings_service
        self._user = user

    async def get_connection_states(self) -> list[MCPConnectionState]:
        servers = await self._settings_service.get_available_mcp_servers()
        user_issuers = await self._connection_repo.get_user_idp_issuers(self._user.id)
        exchanged_by_server = (
            await self._connection_repo.get_exchanged_tokens_by_server(
                tenant_id=self._user.tenant_id,
                user_id=self._user.id,
            )
        )
        now = datetime.now(timezone.utc)

        states: list[MCPConnectionState] = []
        for server in servers:
            states.append(
                self._state_for_server(
                    server_id=server.id,
                    name=server.name,
                    auth_scope=server.auth_scope,
                    expected_idp_issuer=server.expected_idp_issuer,
                    cached_expires_at=exchanged_by_server.get(server.id),
                    user_issuers=user_issuers,
                    now=now,
                )
            )
        return states

    @staticmethod
    def _state_for_server(
        *,
        server_id: UUID,
        name: str,
        auth_scope: str,
        expected_idp_issuer: Optional[str],
        cached_expires_at: Optional[datetime],
        user_issuers: set[str],
        now: datetime,
    ) -> MCPConnectionState:
        expected = (expected_idp_issuer or "").rstrip("/")

        status: MCPConnectionStatusValue
        expires_at: Optional[datetime] = None

        if auth_scope == "static_bearer":
            status = "not_applicable"
        elif cached_expires_at is not None:
            expires_at = cached_expires_at
            status = "connected" if cached_expires_at > now else "expired"
        elif auth_scope == "per_user":
            if not expected:
                # Misconfiguration: operator opted into per_user without an
                # issuer. The broker would refuse at call time; surface a
                # state the admin can act on instead of a generic error.
                status = "idp_mismatch"
            elif expected in user_issuers:
                # SSO session matches; the broker mints on first use.
                status = "connected"
            elif user_issuers:
                status = "idp_mismatch"
            else:
                status = "not_authenticated"
        else:
            # per_tenant with no cached token yet: the tenant service
            # account drives the exchange, so no user action applies.
            status = "not_applicable"

        return MCPConnectionState(
            mcp_server_id=server_id,
            name=name,
            auth_scope=auth_scope,
            expected_idp_issuer=expected_idp_issuer,
            status=status,
            expires_at=expires_at,
        )
