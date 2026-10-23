"""ClientSession variant that negotiates the MCP Apps extension.

MCP Apps (spec revision 2026-01-26) is negotiated by declaring the
``io.modelcontextprotocol/ui`` entry under ``capabilities.extensions`` during
``initialize``. The pinned ``mcp`` 1.x SDK builds its ``ClientCapabilities``
inside ``ClientSession.initialize()`` with no injection hook, so this subclass
attaches the extension by intercepting the outgoing ``InitializeRequest`` in
``send_request`` — ``ClientCapabilities`` is ``extra="allow"``, so the
undeclared ``extensions`` field serializes onto the wire. Shim against SDK
1.x; revisit when the SDK grows first-class extension negotiation.
"""

from typing import Any

from mcp import types
from mcp.client.session import ClientSession

from eneo.mcp_apps.domain.mcp_app_view import MCP_APP_MIME as MCP_APP_MIME

MCP_APPS_EXTENSION_KEY = "io.modelcontextprotocol/ui"

MCP_APPS_PROTOCOL_VERSION = "2026-01-26"


class UiCapableClientSession(ClientSession):
    """ClientSession that declares MCP Apps host support at initialize."""

    async def send_request(self, *args: Any, **kwargs: Any) -> Any:
        request = args[0] if args else kwargs.get("request")
        root = getattr(request, "root", None)
        if isinstance(root, types.InitializeRequest):
            # setattr keeps the undeclared-field write out of static analysis;
            # pydantic stores it in the model's extra fields.
            setattr(
                root.params.capabilities,
                "extensions",
                {MCP_APPS_EXTENSION_KEY: {"mimeTypes": [MCP_APP_MIME]}},
            )
        return await super().send_request(*args, **kwargs)
