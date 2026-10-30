"""Where flows read what every level has stored about a tool.

The facts and the decision on them are the MCP module's
(``unattended_tool_use``). A flow asks about a tool in more than one place:
the classification rule counts the level of the tool's server, and the
decision says whether the tool may be used. Where one publish, or one run's
preflight, asks both, both must be answered from the same rows.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from eneo.mcp_servers.application.unattended_tool_use import (
        StoredToolFacts,
        ToolsOfSpace,
    )


class UnattendedToolFactsSource(Protocol):
    async def read(
        self, *, tenant_id: UUID, space_id: UUID, mcp_server_id: UUID, tool_id: UUID
    ) -> StoredToolFacts: ...


class SpaceToolFactsSource(UnattendedToolFactsSource, Protocol):
    """A facts source that can also list the tools of a space, for the
    editor's list of tools a step can choose from."""

    async def read_tools_of_space(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        max_count: int,
        max_text_bytes: int,
    ) -> ToolsOfSpace: ...


class ToolFactsReadOnce:
    """A facts source that reads the facts of a tool once and answers every
    later question about that tool with what it read.

    Made for one publish or one run preflight and not kept beyond it: within
    it, the classification rule and the decision then judge the same rows.
    ``source`` is asked for at the first read, so a flow without a tool step
    needs none.
    """

    def __init__(self, source: Callable[[], UnattendedToolFactsSource]) -> None:
        self._source = source
        self._read: dict[tuple[UUID, UUID, UUID, UUID], StoredToolFacts] = {}

    async def read(
        self, *, tenant_id: UUID, space_id: UUID, mcp_server_id: UUID, tool_id: UUID
    ) -> StoredToolFacts:
        key = (tenant_id, space_id, mcp_server_id, tool_id)
        if key not in self._read:
            self._read[key] = await self._source().read(
                tenant_id=tenant_id,
                space_id=space_id,
                mcp_server_id=mcp_server_id,
                tool_id=tool_id,
            )
        return self._read[key]
