"""The functions a function step can call in a space.

A function step names a purpose (web search, charts, …) and one tool of the
provider serving it. Which purposes exist is the space's setting; which
provider a run reaches is resolved through the space's flows assistant, as a
turn of that assistant would. This module lists both, for the flows chat's
``list_functions`` tool and the panel's step editor alike.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from eneo.flows.definition import FUNCTION_PURPOSES
from eneo.flows.flow_models import FlowFunctionPublic, FlowFunctionToolPublic

if TYPE_CHECKING:
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
    from eneo.spaces.space import Space

FLOWS_ASSISTANT_PURPOSE = "flows"


class CapabilityServerLookup(Protocol):
    """(assistant_id, purpose) -> the provider serving it, or None."""

    def __call__(
        self, *, assistant_id: UUID, purpose: str
    ) -> Awaitable["MCPServer | None"]: ...


def flows_assistant_id(space: Space) -> UUID | None:
    """The space's flows assistant, which runs resolve providers through."""
    for assistant in space.purpose_assistants:
        if assistant.purpose == FLOWS_ASSISTANT_PURPOSE:
            return assistant.id
    return None


async def list_flow_functions(
    space: Space, capability_server: CapabilityServerLookup
) -> list[FlowFunctionPublic]:
    """Each purpose with its provider's tools as the space's flows assistant reaches them."""
    assistant_id = flows_assistant_id(space)
    functions: list[FlowFunctionPublic] = []
    for purpose in FUNCTION_PURPOSES:
        enabled = space.is_personal() or purpose in space.enabled_capabilities
        server = (
            await capability_server(assistant_id=assistant_id, purpose=purpose)
            if enabled and assistant_id is not None
            else None
        )
        functions.append(
            FlowFunctionPublic(
                purpose=purpose,
                enabled_in_space=enabled,
                available=server is not None,
                provider=server.name if server is not None else None,
                tools=[
                    FlowFunctionToolPublic(
                        name=tool.name,
                        description=tool.description,
                        input_schema=dict(tool.input_schema or {}),
                    )
                    for tool in (server.tools if server is not None else [])
                ],
            )
        )
    return functions
