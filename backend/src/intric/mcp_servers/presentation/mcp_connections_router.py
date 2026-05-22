"""User-facing read-out of MCP connection status (Phase 4).

``GET /api/v1/me/mcp-connections`` returns, for each MCP server the
current user can see, whether the same-IdP broker is in a state where it
can mint a usable bearer for that server. The chat UI surfaces this to
explain "tool X is unavailable because you haven't authenticated to its
provider" without leaking implementation detail.

Status vocabulary:

- ``connected``    — broker has a fresh exchanged token cached for this user.
- ``expired``      — cached token exists but has aged past ``expires_at``.
- ``not_authenticated`` — user has no stored IdP refresh token matching
  the server's ``expected_idp_issuer``; the user must re-login via SSO.
- ``idp_mismatch`` — user logged in via a different IdP than the server
  expects. They cannot reach this server even if they re-authenticate
  unless an operator updates the server config.
- ``not_applicable`` — server is ``static_bearer`` and does not depend on
  user identity. Always reachable when the bearer is configured.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Annotated, Literal, Optional, cast
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from intric.database.tables.idp_user_tokens_table import IdpUserTokens
from intric.database.tables.mcp_exchanged_tokens_table import MCPExchangedTokens
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

ConnectionStatusLiteral = Literal[
    "connected",
    "expired",
    "not_authenticated",
    "idp_mismatch",
    "not_applicable",
]


class MCPConnectionStatusPublic(BaseModel):
    mcp_server_id: UUID
    name: str
    auth_scope: str
    expected_idp_issuer: Optional[str] = None
    status: ConnectionStatusLiteral
    expires_at: Optional[datetime] = None


class MCPConnectionStatusList(BaseModel):
    items: list[MCPConnectionStatusPublic]


_WITH_USER = Depends(get_container(with_user=True))


@router.get(
    "/mcp-connections",
    response_model=MCPConnectionStatusList,
    summary="Per-user MCP server connection state",
)
async def get_my_mcp_connections(
    container: Annotated[Container, _WITH_USER],
) -> MCPConnectionStatusList:
    user = container.user()
    session = cast("AsyncSession", container.session())

    servers = await container.mcp_server_settings_service().get_available_mcp_servers()

    # Pre-load the user's IdP issuers in one query so the per-server loop
    # does not fan out database calls.
    issuer_rows = (
        (
            await session.execute(
                sa.select(IdpUserTokens.idp_issuer).where(
                    IdpUserTokens.user_id == user.id,
                    IdpUserTokens.revoked_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    user_issuers = {row.rstrip("/") for row in issuer_rows}

    # Pre-load active exchanged tokens for this user / tenant in one query.
    now = datetime.now(timezone.utc)
    exchanged_rows = (
        await session.execute(
            sa.select(
                MCPExchangedTokens.mcp_server_id,
                MCPExchangedTokens.subject_type,
                MCPExchangedTokens.expires_at,
            ).where(
                MCPExchangedTokens.tenant_id == user.tenant_id,
                sa.or_(
                    sa.and_(
                        MCPExchangedTokens.subject_type == "user",
                        MCPExchangedTokens.subject_id == user.id,
                    ),
                    sa.and_(
                        MCPExchangedTokens.subject_type == "tenant",
                        MCPExchangedTokens.subject_id == user.tenant_id,
                    ),
                ),
            )
        )
    ).all()
    exchanged_by_server: dict[UUID, tuple[str, datetime]] = {
        row.mcp_server_id: (row.subject_type, row.expires_at) for row in exchanged_rows
    }

    items: list[MCPConnectionStatusPublic] = []
    for server in servers:
        expected = (server.expected_idp_issuer or "").rstrip("/")
        cached = exchanged_by_server.get(server.id)

        status: ConnectionStatusLiteral
        expires_at: Optional[datetime] = None

        if server.auth_scope == "static_bearer":
            status = "not_applicable"
        elif cached is not None:
            _subject_type, cached_exp = cached
            expires_at = cached_exp
            status = "connected" if cached_exp > now else "expired"
        elif server.auth_scope == "per_user":
            if not expected:
                # Misconfiguration: operator opted into per_user without
                # setting an issuer. The broker would refuse at call time;
                # surface that as a connection failure mode the admin can
                # act on without users seeing a generic error.
                status = "idp_mismatch"
            elif expected in user_issuers:
                status = "not_authenticated"
            else:
                status = "idp_mismatch"
        else:
            # per_tenant: no per-user state; tenant service-account drives
            # the exchange. From the user's perspective they are always
            # "connected enough" to call the server; the broker will fail
            # at runtime if the operator hasn't configured credentials.
            status = "not_authenticated"

        items.append(
            MCPConnectionStatusPublic(
                mcp_server_id=server.id,
                name=server.name,
                auth_scope=server.auth_scope,
                expected_idp_issuer=server.expected_idp_issuer,
                status=status,
                expires_at=expires_at,
            )
        )
    return MCPConnectionStatusList(items=items)
