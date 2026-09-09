"""Live tool definitions for built-in capability providers.

A built-in provider is an ``mcp_servers`` row whose endpoint is one of Eneo's
own loopback servers. Its persisted tool rows are a snapshot taken when an
administrator created or refreshed the row, but the loopback server's tools
change with every deploy of Eneo itself. The model must always see the
definitions the running code exposes, so a completion swaps the snapshot for
the live catalog and keeps only the administrator's per-tool decisions
(enabled, display name) from the persisted rows.
"""

from __future__ import annotations

from eneo.mcp_servers.domain.entities.mcp_server import (
    MCPServer,
    MCPServerTool,
    is_builtin_provider,
)


async def with_live_builtin_tools(server: MCPServer) -> list[MCPServerTool]:
    """The server's tools with definitions from the running loopback server.

    External servers and built-ins without a loopback of their purpose keep
    their persisted tools. A live tool without a persisted row (added by a
    deploy the administrator has not refreshed yet) is exposed enabled: the
    definitions are Eneo's own code, which is why the admin refresh path
    auto-approves them as well.
    """
    persisted = list(server.tools or [])
    if not is_builtin_provider(server.http_auth_type):
        return persisted
    from eneo.internal_mcp.registry import INTERNAL_MCP_SERVERS

    internal = next(
        (entry for entry in INTERNAL_MCP_SERVERS if entry.name == server.purpose),
        None,
    )
    if internal is None:
        return persisted

    stored_by_name = {tool.name: tool for tool in persisted}
    live: list[MCPServerTool] = []
    for tool in await internal.mcp.list_tools():
        stored = stored_by_name.get(tool.name)
        live.append(
            MCPServerTool(
                id=stored.id if stored else None,
                mcp_server_id=server.id,
                name=tool.name,
                title=getattr(tool, "title", None),
                display_name=stored.display_name if stored else None,
                description=tool.description,
                input_schema=tool.inputSchema,
                is_enabled_by_default=(
                    stored.is_enabled_by_default if stored else True
                ),
            )
        )
    return live
