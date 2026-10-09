"""Live tool definitions for servers built into Eneo (the bundled tool runtime).

A bundled server's persisted tool rows are a snapshot taken when an
administrator added or refreshed the row, but the runtime's tools change with
every release of the runtime image. Its definitions are Eneo's own code, like
a built-in provider's, so a completion swaps the snapshot for the catalog the
running runtime exposes and keeps only the administrator's per-tool decisions
(enabled, display name) from the persisted rows. The catalog is the same for
every tenant and is cached per process for a short while, so an upgrade is
picked up without anyone pressing sync and without a round-trip per answer.

The persisted rows follow on their own: when the live catalog differs from
them, it is stored as the server's approved definitions, with the views (MCP
Apps) its tools declare. Nobody reviews a bundled server's definitions or
views, for the same reason nobody reviews the rest of Eneo's code, so the
administrator's lists show a new release's tools and a tool's view is shown
without a sync.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.database.database import sessionmanager
from eneo.main.config import get_settings
from eneo.main.logging import get_logger
from eneo.mcp_apps.application.view_snapshots import snapshot_app_views
from eneo.mcp_apps.domain.mcp_app_view import get_ui_resource_uri
from eneo.mcp_apps.infrastructure.repo_impl.mcp_app_view_repo_impl import (
    McpAppViewRepo,
)
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
from eneo.mcp_servers.infrastructure.repo_impl.mcp_server_tool_repo_impl import (
    store_own_catalog,
)

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService

logger = get_logger(__name__)

# How long one process trusts a listed catalog before asking the runtime again.
CATALOG_TTL_SECONDS = 300.0
_catalogs: dict[str, tuple[float, list[dict[str, Any]]]] = {}
# The catalog each server's rows were last brought in line with, so a server
# whose rows are current costs one lookup per answer.
_kept: dict[UUID, str] = {}


def forget_catalogs() -> None:
    """Drop every cached catalog (tests, and after an admin refresh)."""
    _catalogs.clear()
    _kept.clear()


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


def _declares_view(tool_def: dict[str, Any]) -> bool:
    return get_ui_resource_uri(tool_def.get("meta")) is not None


def stored_rows_differ(server: MCPServer, catalog: list[dict[str, Any]]) -> bool:
    """Whether the server's persisted tools are not the live ``catalog``."""
    stored = {tool.name: tool for tool in server.tools or []}
    if stored.keys() != {tool_def["name"] for tool_def in catalog}:
        return True
    views_shown = get_settings().mcp_apps_enabled
    for tool_def in catalog:
        tool = stored[tool_def["name"]]
        if (
            tool.requires_approval
            or tool.removed_from_remote
            or tool.title != tool_def.get("title")
            or tool.has_definition_drift(
                description=tool_def.get("description"),
                input_schema=tool_def.get("input_schema"),
                meta=tool_def.get("meta"),
            )
            or (
                views_shown
                and _declares_view(tool_def)
                and tool.ui_resource_sha256 is None
            )
        ):
            return True
    return False


async def _record_stored_catalog(
    audit_service: "AuditService | None",
    server: MCPServer,
    tool_defs: list[dict[str, Any]],
    view_hashes: dict[str, str],
) -> None:
    """Write the audit entry for a catalog Eneo stored by itself.

    An administrator's approval of an external server's tools is audited with
    the views it puts in force; so is this, with the system as its actor.
    """
    if audit_service is None:
        return
    try:
        await audit_service.log_async(
            tenant_id=server.tenant_id,
            actor_id=None,
            actor_type=ActorType.SYSTEM,
            action=ActionType.MCP_SERVER_UPDATED,
            entity_type=EntityType.MCP_SERVER,
            entity_id=server.id,
            description=(
                f"Stored the current tools of the bundled server '{server.name}'"
            ),
            metadata={
                "actor": {"type": "system", "via": "bundled_tool_runtime"},
                "target": {"id": str(server.id), "name": server.name},
                "tools": [tool_def["name"] for tool_def in tool_defs],
                # The interactive view each tool now shows, by its hash.
                "approved_view_hashes": view_hashes,
            },
        )
    except Exception as exc:
        logger.warning(
            "Could not audit the stored catalog of '%s': %s", server.name, exc
        )


async def keep_stored_catalog_current(
    server: MCPServer,
    catalog: list[dict[str, Any]],
    audit_service: "AuditService | None" = None,
) -> dict[str, str]:
    """Store ``catalog`` as the server's rows when they differ from it.

    Returns the hash of each view stored now, by tool name, so the answer
    that found the difference already shows the view. Tried once per catalog
    and process; a failure is logged and the answer goes on with what the
    rows hold. What was stored is written to the audit log.
    """
    fingerprint = hashlib.sha256(
        json.dumps(catalog, sort_keys=True, default=str).encode()
    ).hexdigest()
    if _kept.get(server.id) == fingerprint:
        return {}
    _kept[server.id] = fingerprint
    if not stored_rows_differ(server, catalog):
        return {}

    # The cached catalog is shared by every tenant; the hashes go on a copy.
    tool_defs = copy.deepcopy(catalog)
    try:
        if get_settings().mcp_apps_enabled and any(map(_declares_view, tool_defs)):
            async with sessionmanager.session() as session:
                async with MCPClient(server) as client:
                    await snapshot_app_views(
                        client, server, tool_defs, McpAppViewRepo(session)
                    )
        await store_own_catalog(server.id, server.tenant_id, tool_defs)
    except Exception as exc:
        logger.warning(
            "Could not store the bundled runtime's catalog for '%s': %s",
            server.name,
            exc,
        )
        return {}
    logger.info("Stored the bundled runtime's current catalog for '%s'", server.name)
    view_hashes = {
        tool_def["name"]: tool_def["ui_resource_sha256"]
        for tool_def in tool_defs
        if tool_def.get("ui_resource_sha256")
    }
    await _record_stored_catalog(audit_service, server, tool_defs, view_hashes)
    return view_hashes


def merge_live_tools(
    server: MCPServer,
    catalog: list[dict[str, Any]],
    view_hashes: dict[str, str] | None = None,
) -> list[MCPServerTool]:
    """``catalog`` as this server's tools, with the admin's decisions kept.

    A live tool without a persisted row (added by a release whose catalog
    could not be stored yet) is exposed enabled: the definitions are Eneo's
    own. ``view_hashes`` are the views stored for this very catalog.
    """
    stored_by_name = {tool.name: tool for tool in server.tools or []}
    live: list[MCPServerTool] = []
    for tool_def in catalog:
        stored = stored_by_name.get(tool_def["name"])
        meta = tool_def.get("meta")
        # The live definition keeps the stored view only while it still
        # declares that resource.
        keeps_view = stored is not None and get_ui_resource_uri(
            stored.meta
        ) == get_ui_resource_uri(meta)
        stored_view = stored.ui_resource_sha256 if stored and keeps_view else None
        live.append(
            MCPServerTool(
                id=stored.id if stored else None,
                mcp_server_id=server.id,
                name=tool_def["name"],
                title=tool_def.get("title"),
                display_name=stored.display_name if stored else None,
                description=tool_def.get("description"),
                input_schema=tool_def.get("input_schema"),
                meta=meta,
                ui_resource_sha256=(
                    (view_hashes or {}).get(tool_def["name"]) or stored_view
                ),
                is_enabled_by_default=(
                    stored.is_enabled_by_default if stored else True
                ),
            )
        )
    return live


async def with_live_bundled_tools(
    server: MCPServer, audit_service: "AuditService | None" = None
) -> MCPServer:
    """``server`` carrying the runtime's live tools; other servers unchanged.

    Returns a shallow copy so the persisted entity never carries the swapped
    list. ``audit_service`` records a catalog that had to be stored on the way.
    """
    if not is_bundled_server(getattr(server, "http_auth_type", None)):
        return server
    catalog = await live_bundled_catalog(server)
    if catalog is None:
        return server
    view_hashes = await keep_stored_catalog_current(server, catalog, audit_service)
    live = copy.copy(server)
    live.tools = merge_live_tools(server, catalog, view_hashes)
    return live
