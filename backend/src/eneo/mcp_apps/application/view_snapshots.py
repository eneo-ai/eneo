"""Snapshots of MCP App views, taken when an administrator syncs a server.

A view is HTML that a server supplies and a user's browser runs. Only a view
an administrator has approved may be served, so the HTML is read here, at
sync, stored under its content hash, and that hash becomes part of the tool
definition under review. Nothing is read from the server when a view is shown.
"""

import json
from typing import TYPE_CHECKING, Any

from eneo.main.logging import get_logger
from eneo.mcp_apps.domain.mcp_app_view import (
    MCP_APP_MIME,
    get_ui_meta,
    get_ui_resource_uri,
    view_content_hash,
)
from eneo.mcp_servers.infrastructure.client.mcp_client import (
    RESOURCE_META_MAX_BYTES,
    MCPClient,
    MCPClientError,
)

if TYPE_CHECKING:
    from eneo.mcp_apps.infrastructure.repo_impl.mcp_app_view_repo_impl import (
        McpAppViewRepo,
    )
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer

logger = get_logger(__name__)

# Views one server may declare. Each is a document of up to
# ``mcp_app_resource_max_bytes`` kept for review, so the count is bounded.
MAX_VIEWS_PER_SERVER = 16


async def _read_view(
    client: MCPClient, server: "MCPServer", uri: str
) -> tuple[str, dict[str, Any] | None] | None:
    """The view's HTML and render policy, or None when it cannot be shown."""
    try:
        resource = await client.read_resource(uri)
    except MCPClientError as exc:
        logger.warning(
            "Could not read app view %s from '%s': %s", uri, server.name, exc
        )
        return None

    mime_type = str(resource.get("mime_type") or "").replace(" ", "").lower()
    if mime_type != MCP_APP_MIME:
        logger.warning(
            "App view %s from '%s' has mimetype %r, expected %r",
            uri,
            server.name,
            resource.get("mime_type"),
            MCP_APP_MIME,
        )
        return None
    html = resource.get("text")
    if not html:
        return None

    ui_meta = get_ui_meta(resource.get("meta"))
    if ui_meta is not None:
        # A truncated CSP declaration must never be rendered permissively:
        # an oversized policy block is refused outright instead of trimmed.
        ui_meta_bytes = len(json.dumps(ui_meta, ensure_ascii=False).encode())
        if ui_meta_bytes > RESOURCE_META_MAX_BYTES:
            logger.warning(
                "App view %s from '%s' declares %d bytes of ui metadata "
                "(max %d); it will not be shown",
                uri,
                server.name,
                ui_meta_bytes,
                RESOURCE_META_MAX_BYTES,
            )
            return None
    return html, ui_meta


async def snapshot_app_views(
    client: MCPClient,
    server: "MCPServer",
    tool_defs: list[dict[str, Any]],
    repo: "McpAppViewRepo",
) -> None:
    """Store the views ``tool_defs`` declare and note each one's hash.

    A definition whose view was stored gains ``ui_resource_sha256``. One whose
    view could not be read or stored gains nothing, and the tool then shows no
    view; a tool sync never fails over a view.
    """
    uris: list[str] = []
    for tool_def in tool_defs:
        uri = get_ui_resource_uri(tool_def.get("meta"))
        if uri is not None and uri not in uris:
            uris.append(uri)
    if len(uris) > MAX_VIEWS_PER_SERVER:
        logger.warning(
            "'%s' declares %d app views; only the first %d are kept",
            server.name,
            len(uris),
            MAX_VIEWS_PER_SERVER,
        )
        uris = uris[:MAX_VIEWS_PER_SERVER]

    hashes: dict[str, str] = {}
    for uri in uris:
        view = await _read_view(client, server, uri)
        if view is None:
            continue
        html, ui_meta = view
        content_hash = view_content_hash(html, ui_meta)
        try:
            await repo.upsert(
                tenant_id=server.tenant_id,
                mcp_server_id=server.id,
                uri=uri,
                content_hash=content_hash,
                html=html,
                ui_meta=ui_meta,
            )
        except Exception as exc:
            logger.warning(
                "Could not store app view %s from '%s': %s", uri, server.name, exc
            )
            continue
        hashes[uri] = content_hash

    for tool_def in tool_defs:
        uri = get_ui_resource_uri(tool_def.get("meta"))
        if uri is not None and uri in hashes:
            tool_def["ui_resource_sha256"] = hashes[uri]
