# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


import copy
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.widgets.domain.widget import Widget

if TYPE_CHECKING:
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool


def _no_external_tools() -> dict[UUID, frozenset[UUID]]:
    return {}


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
    # Server id to tool ids: the tools outside Eneo an admin acknowledged for
    # this widget, empty when the tenant policy allows none. Decided per
    # request from the widget row, so never serialised into a delegated token.
    external_tools: dict[UUID, frozenset[UUID]] = Field(
        default_factory=_no_external_tools, exclude=True, repr=False
    )

    def reachable_servers(self, servers: Sequence["MCPServer"]) -> list["MCPServer"]:
        """``servers`` as this visitor's turn may call them.

        Eneo's own servers pass untouched. An external server is left out
        unless a tool switched on there is acknowledged, so the turn never
        contacts it for nothing; on one kept, each tool outside the
        acknowledgement is switched off on a copy rather than dropped, since
        the MCP proxy stages a listed tool missing from the catalog as newly
        discovered.
        """
        reachable: list["MCPServer"] = []
        for server in servers:
            if server.is_internal:
                reachable.append(server)
                continue
            granted = self.external_tools.get(server.id)
            if granted is None or not server.tools_loaded:
                continue
            tools = [
                tool if tool.id in granted else _switched_off(tool)
                for tool in server.tools
            ]
            if not any(tool.is_enabled for tool in tools):
                continue
            narrowed = copy.copy(server)
            narrowed.tools = tools
            reachable.append(narrowed)
        return reachable


def _switched_off(tool: "MCPServerTool") -> "MCPServerTool":
    withheld = copy.copy(tool)
    withheld.enabled_override = False
    return withheld


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
