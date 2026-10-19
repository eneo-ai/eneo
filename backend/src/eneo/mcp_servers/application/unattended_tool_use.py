"""May a caller that runs with nobody watching call this tool for this space?

The levels are asked in the order a person meets them: the instance admin's
server, the instance admin's tool, then the space. The answer is the first
level that refuses, so the caller can say who can change it. A personal space
is the answer before any level is asked: there, nobody at any level can.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, Protocol, TypeAlias, TypeVar
from uuid import UUID

from eneo.mcp_servers.application.capability_resolver import (
    ClassifiedServer,
    meets_security_classification,
)
from eneo.mcp_servers.domain.credential_transport import (
    credential_transport_violation,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    MCPServer,
    MCPServerTool,
    is_general_server,
)
from eneo.mcp_servers.domain.tool_switch import ToolSwitch, tool_switch
from eneo.mcp_servers.domain.unattended_tool_refusal import UnattendedToolRefusal

if TYPE_CHECKING:
    from eneo.security_classifications.domain.entities.security_classification import (
        SecurityClassification,
    )


class UnattendedServer(ClassifiedServer, Protocol):
    """What the decision reads of a server."""

    @property
    def id(self) -> UUID: ...
    @property
    def is_enabled(self) -> bool: ...
    @property
    def purpose(self) -> str: ...
    @property
    def http_auth_type(self) -> str: ...
    @property
    def http_url(self) -> str: ...
    @property
    def forward_identity(self) -> bool: ...


class UnattendedTool(Protocol):
    """What the decision reads of a tool."""

    @property
    def mcp_server_id(self) -> UUID: ...
    @property
    def removed_from_remote(self) -> bool: ...
    @property
    def requires_approval(self) -> bool: ...
    @property
    def is_enabled_by_default(self) -> bool: ...


ServerT = TypeVar("ServerT", bound=UnattendedServer | None, covariant=True)
ToolT = TypeVar("ToolT", bound=UnattendedTool | None, covariant=True)


@dataclass(frozen=True)
class UnattendedToolFacts(Generic[ServerT, ToolT]):
    """What every level has stored about one tool for one space.

    ``tool`` is the server's own tool row: a projection made for a space or an
    assistant has already applied switches and dropped facts this decision
    reads. None for ``tenant_setting`` or ``space_override`` means that level
    has set no switch. The server and tool types say how much of their rows
    was read (the whole rows for one tool, the list's columns for a list) and
    whether they can be missing: a read of one tool may find neither, a list
    joins both, so its facts always hold them.
    """

    server: ServerT
    tool: ToolT
    tenant_setting: bool | None
    space_is_personal: bool
    server_in_space: bool
    space_override: bool | None
    space_security_classification: "SecurityClassification | None"


@dataclass(frozen=True, slots=True)
class ListedServer:
    """What a list of a space's tools reads of a server: what the decision
    and an option need (the address only for the decision), and not its
    credentials or configuration."""

    id: UUID
    name: str
    is_enabled: bool
    purpose: str
    http_auth_type: str
    http_url: str
    forward_identity: bool
    # The server's own: a list reads general servers only, and only a
    # built-in provider runs on a catalog model whose level it would take
    # (ck_mcp_servers_internal_image_model).
    effective_security_classification: "SecurityClassification | None"


@dataclass(frozen=True, slots=True)
class ListedTool:
    """What a list of a space's tools reads of a tool: its approved
    definition and the decision's columns, not a pending definition."""

    id: UUID
    mcp_server_id: UUID
    name: str
    description: str | None
    input_schema: dict[str, object] | None
    is_enabled_by_default: bool
    requires_approval: bool
    removed_from_remote: bool


StoredToolFacts: TypeAlias = UnattendedToolFacts[MCPServer | None, MCPServerTool | None]
ListedToolFacts: TypeAlias = UnattendedToolFacts[ListedServer, ListedTool]


@dataclass(frozen=True)
class ToolsOfSpace:
    """The first tools of a space's list, up to the row where a bound is
    crossed, and the bytes of the counted fields together: the server name, the
    tool name, the approved description and the approved input schema, which
    an option returns, and the server's address, which the decision reads.

    The whole list is over a bound exactly when these facts number more than
    the read's ``max_count`` or their ``text_bytes`` exceed its
    ``max_text_bytes``.
    """

    facts: list[ListedToolFacts]
    text_bytes: int


def unattended_tool_refusal(
    facts: UnattendedToolFacts[UnattendedServer | None, UnattendedTool | None],
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
    if not is_general_server(
        purpose=server.purpose, http_auth_type=server.http_auth_type
    ):
        return UnattendedToolRefusal.SERVER_NOT_GENERAL
    if server.forward_identity:
        return UnattendedToolRefusal.SERVER_FORWARDS_IDENTITY
    if (
        credential_transport_violation(server.http_auth_type, server.http_url)
        is not None
    ):
        return UnattendedToolRefusal.SERVER_CREDENTIAL_NEEDS_HTTPS

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
