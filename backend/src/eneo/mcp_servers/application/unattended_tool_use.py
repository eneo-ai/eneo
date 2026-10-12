"""May a caller that runs with nobody watching call this tool for this space?

The levels are asked in the order a person meets them: the instance admin's
server, the instance admin's tool, then the space. The answer is the first
level that refuses, so the caller can say who can change it. A personal space
is the answer before any level is asked: there, nobody at any level can.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from eneo.mcp_servers.application.capability_resolver import (
    meets_security_classification,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    is_builtin_provider,
    is_capability_purpose,
)
from eneo.mcp_servers.domain.tool_switch import ToolSwitch, tool_switch

if TYPE_CHECKING:
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
    from eneo.security_classifications.domain.entities.security_classification import (
        SecurityClassification,
    )


class UnattendedToolRefusal(StrEnum):
    # The instance admin's server.
    SERVER_NOT_FOUND = "server_not_found"
    SERVER_DISABLED = "server_disabled"
    # A capability provider or one of Eneo's own servers: reached through its
    # capability, never as a tool somebody picked.
    SERVER_NOT_GENERAL = "server_not_general"
    # The server answers as the acting user; an unattended caller has none
    # whose rights the answer may carry.
    SERVER_FORWARDS_IDENTITY = "server_forwards_identity"
    # The instance admin's tool.
    TOOL_NOT_FOUND = "tool_not_found"
    TOOL_REMOVED_AT_SERVER = "tool_removed_at_server"
    # New, or changed at the server, and no admin has looked at it yet. The
    # call goes to the server as it is now, so the approved definition says
    # nothing about what would answer.
    TOOL_WAITING_FOR_REVIEW = "tool_waiting_for_review"
    TOOL_SWITCHED_OFF = "tool_switched_off"
    # The space.
    SPACE_IS_PERSONAL = "space_is_personal"
    SERVER_NOT_IN_SPACE = "server_not_in_space"
    TOOL_SWITCHED_OFF_IN_SPACE = "tool_switched_off_in_space"
    SERVER_BELOW_SPACE_CLASSIFICATION = "server_below_space_classification"


@dataclass(frozen=True)
class UnattendedToolFacts:
    """What every level has stored about one tool for one space.

    ``tool`` is the server's own tool row: a projection made for a space or an
    assistant has already applied switches and dropped facts this decision
    reads. None for ``tenant_setting`` or ``space_override`` means that level
    has set no switch.
    """

    server: "MCPServer | None"
    tool: "MCPServerTool | None"
    tenant_setting: bool | None
    space_is_personal: bool
    server_in_space: bool
    space_override: bool | None
    space_security_classification: "SecurityClassification | None"


def unattended_tool_refusal(
    facts: UnattendedToolFacts,
) -> UnattendedToolRefusal | None:
    """The first level that refuses the call; None when every level allows it."""
    # A personal space has no chain of levels: nothing an administrator
    # changes lets the call out, so naming a level would send the author to
    # somebody who cannot help. The flow has to live in a shared space.
    if facts.space_is_personal:
        return UnattendedToolRefusal.SPACE_IS_PERSONAL

    server, tool = facts.server, facts.tool
    if server is None:
        return UnattendedToolRefusal.SERVER_NOT_FOUND
    if not server.is_enabled:
        return UnattendedToolRefusal.SERVER_DISABLED
    if is_capability_purpose(server.purpose) or is_builtin_provider(
        server.http_auth_type
    ):
        return UnattendedToolRefusal.SERVER_NOT_GENERAL
    if server.forward_identity:
        return UnattendedToolRefusal.SERVER_FORWARDS_IDENTITY

    if tool is None or tool.mcp_server_id != server.id:
        return UnattendedToolRefusal.TOOL_NOT_FOUND
    if tool.removed_from_remote:
        return UnattendedToolRefusal.TOOL_REMOVED_AT_SERVER
    if tool.requires_approval:
        return UnattendedToolRefusal.TOOL_WAITING_FOR_REVIEW
    switch = tool_switch(
        enabled_by_default=tool.is_enabled_by_default,
        tenant_setting=facts.tenant_setting,
        space_override=facts.space_override,
    )
    if switch in (ToolSwitch.OFF_FOR_ALL, ToolSwitch.OFF_BY_DEFAULT):
        return UnattendedToolRefusal.TOOL_SWITCHED_OFF

    if not facts.server_in_space:
        return UnattendedToolRefusal.SERVER_NOT_IN_SPACE
    if switch is ToolSwitch.OFF_IN_SPACE:
        return UnattendedToolRefusal.TOOL_SWITCHED_OFF_IN_SPACE
    if not meets_security_classification(server, facts.space_security_classification):
        return UnattendedToolRefusal.SERVER_BELOW_SPACE_CLASSIFICATION
    return None
