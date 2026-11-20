# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.widgets.domain.widget import Widget

if TYPE_CHECKING:
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool


def external_tools_for_widget(server: "MCPServer") -> list["MCPServerTool"]:
    """Enabled assistant tools on an external server, for display and visitor turns."""
    if server.is_internal or not server.is_enabled or not server.tools_loaded:
        return []
    return [tool for tool in server.tools if tool.is_enabled]


class WidgetVisitorContext(BaseModel):
    """Carried on the synthetic visitor ``UserInDB`` (``active_widget``).

    Mirrors ``active_api_key`` for service keys: the only access path into a
    space is the widget itself, and sessions are owned by widget + visitor.
    """

    model_config = ConfigDict(frozen=True)

    widget_id: UUID
    visitor_id: UUID
    tenant_id: UUID
    space_id: UUID
    target_id: UUID
    token_generation: int = Field(ge=0, strict=True)
    preview: bool = Field(default=False, strict=True)
    # Retention 0: conversation content must never be committed, so the
    # session service keeps placeholders inside the request transaction.
    never_persist: bool = False
    # Request-scoped policy supplied by build_visitor_user, also for previews.
    allow_external_tools: bool = Field(default=False, exclude=True)

    def reachable_servers(self, servers: Sequence["MCPServer"]) -> list["MCPServer"]:
        """Apply the organisation's widget policy to the assistant's current servers."""
        return [
            server
            for server in servers
            if server.is_internal
            or (self.allow_external_tools and external_tools_for_widget(server))
        ]


@dataclass(frozen=True)
class VisitorClaims:
    widget_id: UUID
    tenant_id: UUID
    visitor_id: UUID
    generation: int
    issued_at: datetime
    expires_at: datetime
    jti: str
    # Minted for an editor's live preview: also admits a draft widget.
    preview: bool = False


@dataclass(frozen=True)
class WidgetPrincipal:
    """The authenticated party on the anonymous widget surface.

    Deliberately not a ``UserInDB``: nothing downstream may mistake a visitor
    for a user, and there is no users row to key ownership on.
    """

    widget: Widget
    visitor_id: UUID
    claims: VisitorClaims

    @property
    def tenant_id(self) -> UUID:
        return self.widget.tenant_id
