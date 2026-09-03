"""Resolve a tenant's active MCP provider for a capability purpose.

Capabilities (web search, image generation) are configured through the
ordinary MCP inheritance chain (admin activates a provider, spaces include
it, assistants attach it), but the attached server is a capability marker,
not a provider pin: at ask time the tenant's currently active provider for
that purpose (is_enabled=true, at most one per tenant and purpose via partial
unique index) is resolved and attached in its place. Switching providers
therefore never requires touching spaces or assistants.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from eneo.database.tables.mcp_server_table import (
    MCPServers as MCPServersTable,
)
from eneo.database.tables.mcp_server_table import (
    MCPServerToolSettings,
)
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationDBModel,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    CAPABILITY_PURPOSES,
    is_capability_purpose,
)
from eneo.mcp_servers.infrastructure.mappers.mcp_server_mapper import MCPServerMapper

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from eneo.mcp_servers.domain.entities.mcp_server import (
        MCPServer,
        MCPServerTool,
    )


def usable_capability_tools(server: "MCPServer") -> list["MCPServerTool"]:
    """Tools the proxy would actually expose: enabled, still on the remote,
    and with an admin-approved definition."""
    return [
        tool
        for tool in server.tools
        if tool.is_enabled_by_default
        and not tool.removed_from_remote
        and (tool.description is not None or tool.input_schema is not None)
    ]


async def get_active_capability_server(
    session: "AsyncSession", tenant_id: UUID, purpose: str
) -> "MCPServer | None":
    """Return the tenant's active provider for ``purpose``, or None.

    Tools carry the tenant-level enablement overlay so downstream consumers
    (the MCP proxy, usability checks) see effective enablement.
    """
    query = (
        sa.select(MCPServersTable)
        .where(
            MCPServersTable.tenant_id == tenant_id,
            MCPServersTable.purpose == purpose,
            MCPServersTable.is_enabled == True,  # noqa: E712
        )
        .options(
            selectinload(MCPServersTable.tools),
            selectinload(MCPServersTable.security_classification).selectinload(
                SecurityClassificationDBModel.tenant
            ),
        )
    )
    record = await session.scalar(query)
    if record is None:
        return None

    server = MCPServerMapper.to_entity(record)

    tool_ids = [tool.id for tool in server.tools]
    if tool_ids:
        settings_stmt = sa.select(
            MCPServerToolSettings.mcp_server_tool_id,
            MCPServerToolSettings.is_enabled,
        ).where(
            MCPServerToolSettings.tenant_id == tenant_id,
            MCPServerToolSettings.mcp_server_tool_id.in_(tool_ids),
        )
        settings_rows = (await session.execute(settings_stmt)).all()
        tenant_settings = {tool_id: enabled for tool_id, enabled in settings_rows}
        for tool in server.tools:
            if tool.id in tenant_settings:
                tool.is_enabled_by_default = tenant_settings[tool.id]

    return server


@dataclass(frozen=True)
class CapabilityResolution:
    """Attached servers split into general servers and resolved providers."""

    general_servers: list["MCPServer"]
    capability_servers: list["MCPServer"]


async def resolve_capability_servers(
    session: "AsyncSession",
    tenant_id: UUID,
    attached_servers: Sequence["MCPServer"],
    *,
    supports_tool_calling: bool,
) -> CapabilityResolution:
    """Replace attached capability markers with the tenant's active providers.

    Capability-purpose servers among ``attached_servers`` are stripped (they
    may be stale or deactivated) and, for every requested purpose in
    ``CAPABILITY_PURPOSES`` order, the currently active provider is attached
    in their place when it exists, has usable tools, and the model can call
    tools. A purpose without an active provider is silently unavailable.
    """
    general_servers = [
        server
        for server in attached_servers
        if not is_capability_purpose(server.purpose)
    ]
    requested_purposes = {
        server.purpose
        for server in attached_servers
        if is_capability_purpose(server.purpose)
    }
    capability_servers: list["MCPServer"] = []
    if requested_purposes and supports_tool_calling:
        for purpose in CAPABILITY_PURPOSES:
            if purpose not in requested_purposes:
                continue
            active_provider = await get_active_capability_server(
                session, tenant_id, purpose
            )
            if active_provider is not None and usable_capability_tools(active_provider):
                capability_servers.append(active_provider)
    return CapabilityResolution(
        general_servers=general_servers, capability_servers=capability_servers
    )
