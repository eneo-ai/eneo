"""One tool a flow's space offers a step, with what the decision says about it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias
from uuid import UUID

from eneo.flows.domain.tool_facts import SpaceToolFactsSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_security_classification import tool_server_classification_level
from eneo.main.exceptions import FileTooLargeException
from eneo.mcp_servers.application.unattended_tool_use import (
    ListedToolFacts,
    UnattendedToolRefusal,
    unattended_tool_refusal,
)

# What one list answer may hold. The per-server catalog limits bound one
# server, but a space activates any number of servers, so without a total the
# answer (and the memory to build it) grows with the space. A safety bound
# like MCP_TOOL_CATALOG_HARD_MAX_COUNT, not a policy an administrator tunes:
# a space over it is refused, never listed in part, since a part would hide
# tools without saying so. The byte bound counts the server name, the tool
# name, the approved description and the approved input schema an item returns
# (see LISTED_TEXT_FIELDS), because an MCP server bounds a tool's name only
# through the size of the whole definition. It also counts the server's
# address, which the decision reads for every tool and no item returns.
FLOW_TOOL_OPTIONS_MAX_COUNT = 1000
FLOW_TOOL_OPTIONS_MAX_TEXT_BYTES = 8 * 1024 * 1024
TOOL_OPTIONS_TOO_LARGE_MESSAGE = (
    "The space offers more tools than the editor can list. A space "
    "administrator can switch off the MCP servers flows do not need."
)


@dataclass(frozen=True, slots=True)
class FlowToolOption:
    mcp_server_id: UUID
    mcp_server_name: str
    mcp_server_security_level: int | None
    tool_id: UUID
    tool_name: str
    tool_description: str | None
    input_schema: dict[str, object] | None
    refusal: UnattendedToolRefusal | None


@dataclass(frozen=True, slots=True)
class FlowToolOptions:
    options: list[FlowToolOption]
    # The organization's switch the classification rule reads: while it is
    # off no level applies, so no option carries one.
    security_classifications_enabled: bool


def flow_tool_option(
    facts: ListedToolFacts, *, security_enabled: bool
) -> FlowToolOption:
    server, tool = facts.server, facts.tool
    return FlowToolOption(
        mcp_server_id=server.id,
        mcp_server_name=server.name,
        mcp_server_security_level=(
            tool_server_classification_level(server) if security_enabled else None
        ),
        tool_id=tool.id,
        tool_name=tool.name,
        tool_description=tool.description,
        input_schema=tool.input_schema,
        refusal=unattended_tool_refusal(facts),
    )


@dataclass(frozen=True, slots=True)
class FlowToolOptionsOverBound:
    """The space's tools exceed a list bound, so none of them are listed."""


SpaceToolOptions: TypeAlias = FlowToolOptions | FlowToolOptionsOverBound


async def read_space_tool_options(
    reader: SpaceToolFactsSource,
    *,
    tenant_id: UUID,
    space_id: UUID,
    security_enabled: bool,
) -> SpaceToolOptions:
    """The options for every tool of the general servers ``space_id`` has
    activated, in the reader's order, or that they exceed a bound.

    The reader returns at most one tool past a bound, so the outcome is
    decided on what it returned: more tools than the count bound, or more
    bytes than the byte bound, means the whole list is over it.
    """
    listed = await reader.read_tools_of_space(
        tenant_id=tenant_id,
        space_id=space_id,
        max_count=FLOW_TOOL_OPTIONS_MAX_COUNT,
        max_text_bytes=FLOW_TOOL_OPTIONS_MAX_TEXT_BYTES,
    )
    if (
        len(listed.facts) > FLOW_TOOL_OPTIONS_MAX_COUNT
        or listed.text_bytes > FLOW_TOOL_OPTIONS_MAX_TEXT_BYTES
    ):
        return FlowToolOptionsOverBound()
    return FlowToolOptions(
        options=[
            flow_tool_option(fact, security_enabled=security_enabled)
            for fact in listed.facts
        ],
        security_classifications_enabled=security_enabled,
    )


async def read_flow_tool_options(
    reader: SpaceToolFactsSource,
    *,
    tenant_id: UUID,
    space_id: UUID,
    security_enabled: bool,
) -> FlowToolOptions:
    """``read_space_tool_options`` for the editor's list, refused when the
    tools exceed a bound."""
    options = await read_space_tool_options(
        reader,
        tenant_id=tenant_id,
        space_id=space_id,
        security_enabled=security_enabled,
    )
    if isinstance(options, FlowToolOptionsOverBound):
        raise FileTooLargeException(
            TOOL_OPTIONS_TOO_LARGE_MESSAGE,
            code=FlowApiErrorCode.TOOL_OPTIONS_TOO_LARGE.value,
            context={
                "max_tool_count": FLOW_TOOL_OPTIONS_MAX_COUNT,
                "max_text_bytes": FLOW_TOOL_OPTIONS_MAX_TEXT_BYTES,
            },
        )
    return options
