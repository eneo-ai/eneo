"""User-facing read-out of MCP connection status.

Thin presentation layer over :class:`MCPConnectionService`; the status
vocabulary and its semantics live there.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from eneo.main.container.container import Container
from eneo.mcp_servers.application.mcp_connection_service import (
    MCPConnectionStatusValue,
)
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()

_WITH_USER = Depends(get_container(with_user=True))


class MCPConnectionStatusPublic(BaseModel):
    mcp_server_id: UUID
    name: str
    auth_scope: str
    expected_idp_issuer: Optional[str] = None
    status: MCPConnectionStatusValue
    expires_at: Optional[datetime] = None


class MCPConnectionStatusList(BaseModel):
    items: list[MCPConnectionStatusPublic]


@router.get(
    "/mcp-connections",
    description="Per-user MCP server connection state.",
    response_model=MCPConnectionStatusList,
    responses=responses.get_responses([401]),
)
async def get_my_mcp_connections(
    container: Annotated[Container, _WITH_USER],
) -> MCPConnectionStatusList:
    """Return the broker connection status for every visible MCP server."""
    service = container.mcp_connection_service()
    states = await service.get_connection_states()
    return MCPConnectionStatusList(
        items=[
            MCPConnectionStatusPublic(
                mcp_server_id=state.mcp_server_id,
                name=state.name,
                auth_scope=state.auth_scope,
                expected_idp_issuer=state.expected_idp_issuer,
                status=state.status,
                expires_at=state.expires_at,
            )
            for state in states
        ]
    )
