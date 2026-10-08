"""Domain types for MCP App views (spec revision 2026-01-26).

A tool opts into a UI by carrying ``_meta.ui.resourceUri`` (a ``ui://`` URI);
the referenced resource's ``_meta.ui`` block holds the render policy the host
must enforce (csp, permissions, prefersBorder). The capability negotiated at
initialize uses the namespaced ``io.modelcontextprotocol/ui`` key, but the
``_meta`` blocks themselves use the plain ``ui`` key per the spec.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, cast
from uuid import UUID

UI_URI_SCHEME = "ui://"

# Exact mimetype required by the MCP Apps extension for view HTML. The profile
# parameter is part of the contract; plain text/html does not qualify.
MCP_APP_MIME = "text/html;profile=mcp-app"


def get_ui_meta(meta: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Return the ``ui`` block of an MCP ``_meta`` dict, if declared."""
    if not isinstance(meta, dict):
        return None
    ui = meta.get("ui")
    if isinstance(ui, dict):
        return cast(dict[str, Any], ui)
    return None


def get_ui_resource_uri(meta: Optional[dict[str, Any]]) -> Optional[str]:
    """Return a tool's declared ``ui://`` template URI, if valid.

    Servers built on earlier revisions of the extension declare it under the
    flat ``ui/resourceUri`` key; the nested form wins when both are present.
    """
    ui = get_ui_meta(meta)
    uri = ui.get("resourceUri") if ui is not None else None
    if uri is None and isinstance(meta, dict):
        uri = meta.get("ui/resourceUri")
    if isinstance(uri, str) and uri.startswith(UI_URI_SCHEME):
        return uri
    return None


def is_model_visible(meta: Optional[dict[str, Any]]) -> bool:
    """Whether a tool may be offered to the model.

    A tool is offered to both the model and its view unless its
    ``_meta.ui.visibility`` says otherwise; one that lists only ``app`` is
    callable from the view alone and must never reach the model.
    """
    ui = get_ui_meta(meta)
    visibility = ui.get("visibility") if ui is not None else None
    if not isinstance(visibility, list):
        return True
    return "model" in cast(list[object], visibility)


def view_content_hash(html: str, ui_meta: Optional[dict[str, Any]]) -> str:
    """The identity of one view: its HTML together with its render policy.

    The policy (CSP domains, permissions) decides what the HTML may do, so a
    server that keeps the HTML and widens the policy has changed the view.
    """
    policy = json.dumps(ui_meta or {}, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256()
    digest.update(html.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(policy.encode("utf-8"))
    return digest.hexdigest()


def is_app_visible(meta: Optional[dict[str, Any]]) -> bool:
    """Whether a tool may be called from its server's views.

    Like the model, a view may call a tool unless ``_meta.ui.visibility``
    leaves it out.
    """
    ui = get_ui_meta(meta)
    visibility = ui.get("visibility") if ui is not None else None
    if not isinstance(visibility, list):
        return True
    return "app" in cast(list[object], visibility)


@dataclass(frozen=True)
class McpAppViewInfo:
    """What a rendered tool call needs to reference its cached view."""

    view_id: UUID
    mcp_server_id: UUID
    uri: str
    mime_type: str
    ui_meta: Optional[dict[str, Any]]


@dataclass(frozen=True)
class McpAppView:
    """One cached view row, as read back for serving."""

    id: UUID
    tenant_id: UUID
    mcp_server_id: UUID
    uri: str
    content_hash: str
    html: str
    ui_meta: Optional[dict[str, Any]]
    fetched_at: datetime
