"""Live tool definitions for servers built into Eneo (the bundled tool runtime).

A bundled server's persisted tool rows are a snapshot taken when an
administrator added or refreshed the row, but the runtime's tools change with
every release of the runtime image. Its definitions are Eneo's own code, like
a built-in provider's, so a completion swaps the snapshot for the catalog the
running runtime exposes and keeps only the administrator's per-tool decisions
(enabled, display name) from the persisted rows. The catalog is the same for
every tenant and is cached per process for a short while, so an upgrade is
picked up without anyone pressing sync and without a round-trip per answer.
"""

from __future__ import annotations

import copy
import time
from typing import Any

from eneo.main.logging import get_logger
from eneo.mcp_servers.domain.entities.mcp_server import (
    MCPServer,
    MCPServerTool,
    is_bundled_server,
)
from eneo.mcp_servers.infrastructure.client.mcp_client import (
    MCPClient,
    MCPClientError,
    endpoint_url,
)

logger = get_logger(__name__)

# How long one process trusts a listed catalog before asking the runtime again.
CATALOG_TTL_SECONDS = 300.0
_catalogs: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def forget_catalogs() -> None:
    """Drop every cached catalog (tests, and after an admin refresh)."""
    _catalogs.clear()


async def live_bundled_catalog(server: MCPServer) -> list[dict[str, Any]] | None:
    """The runtime's current tool definitions for ``server``'s endpoint.

    None when the runtime cannot be reached; the caller then keeps the
    persisted snapshot so an answer never fails on a listing.
    """
    endpoint = endpoint_url(server)
    cached = _catalogs.get(endpoint)
    now = time.monotonic()
    if cached is not None and now - cached[0] < CATALOG_TTL_SECONDS:
        return cached[1]
    try:
        async with MCPClient(server) as client:
            catalog = await client.list_tools()
    except MCPClientError as exc:
        logger.warning(
            "Could not list the bundled runtime's tools at %s: %s", endpoint, exc
        )
        return None
    _catalogs[endpoint] = (now, catalog)
    return catalog


def merge_live_tools(
    server: MCPServer, catalog: list[dict[str, Any]]
) -> list[MCPServerTool]:
    """``catalog`` as this server's tools, with the admin's decisions kept.

    A live tool without a persisted row (added by a release the administrator
    has not refreshed yet) is exposed enabled: the definitions are Eneo's own.
    """
    stored_by_name = {tool.name: tool for tool in server.tools or []}
    live: list[MCPServerTool] = []
    for tool_def in catalog:
        stored = stored_by_name.get(tool_def["name"])
        live.append(
            MCPServerTool(
                id=stored.id if stored else None,
                mcp_server_id=server.id,
                name=tool_def["name"],
                title=tool_def.get("title"),
                display_name=stored.display_name if stored else None,
                description=tool_def.get("description"),
                input_schema=tool_def.get("input_schema"),
                is_enabled_by_default=(
                    stored.is_enabled_by_default if stored else True
                ),
            )
        )
    return live


async def with_live_bundled_tools(server: MCPServer) -> MCPServer:
    """``server`` carrying the runtime's live tools; other servers unchanged.

    Returns a shallow copy so the persisted entity never carries the swapped
    list.
    """
    if not is_bundled_server(getattr(server, "http_auth_type", None)):
        return server
    catalog = await live_bundled_catalog(server)
    if catalog is None:
        return server
    live = copy.copy(server)
    live.tools = merge_live_tools(server, catalog)
    return live
