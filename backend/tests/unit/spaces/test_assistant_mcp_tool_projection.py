"""What an assistant is offered after the tenant, space and assistant switches."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from eneo.database.tables.mcp_server_table import MCPServerTools
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session import MCPProxySession
from eneo.spaces.space_repo import SpaceRepository

_SCHEMA: dict[str, object] = {"type": "object", "properties": {}}


def _row(server_id: UUID, **facts: object) -> MCPServerTools:
    now = datetime.now(timezone.utc)
    return MCPServerTools(
        id=uuid4(),
        mcp_server_id=server_id,
        name="lookup_case",
        is_enabled_by_default=True,
        created_at=now,
        updated_at=now,
        **facts,
    )


def _projected(*, server_id: UUID, row: MCPServerTools) -> MCPServerTool:
    """The tool an assistant that switched it on gets from the projection."""
    server = MCPServer(
        id=server_id,
        tenant_id=uuid4(),
        name="server",
        http_url="https://tools.example.org/mcp",
    )
    [projected] = SpaceRepository._project_assistant_mcp_server_tools(
        mcp_servers=[server],
        tools_db=[row],
        tenant_tool_settings={},
        space_tool_overrides={},
        assistant_tool_overrides={row.id: True},
    )
    [tool] = projected.tools
    return tool


# Kills the mutant that rebuilds a tool without its review state: the proxy
# hides a tool by "removed at the server" and "never approved", and a rebuilt
# tool that has lost both was offered to the model again.
@pytest.mark.parametrize(
    ("description", "input_schema", "requires_approval", "removed", "offered"),
    [
        pytest.param("Reads a case.", _SCHEMA, False, False, True, id="approved"),
        # Kills "every tool counts as waiting": approval is a fact of the row.
        pytest.param(None, None, False, False, True, id="approved-bare"),
        pytest.param("Reads a case.", _SCHEMA, True, True, False, id="removed"),
        pytest.param(None, None, True, False, False, id="never-approved"),
        # A changed definition waits for the admin; the approved one stays in use.
        pytest.param("Reads a case.", _SCHEMA, True, False, True, id="change-waiting"),
    ],
)
def test_the_projection_keeps_what_hides_a_tool(
    description: str | None,
    input_schema: dict[str, object] | None,
    requires_approval: bool,
    removed: bool,
    offered: bool,
) -> None:
    server_id = uuid4()
    row = _row(
        server_id,
        description=description,
        input_schema=input_schema,
        requires_approval=requires_approval,
        removed_from_remote=removed,
    )

    tool = _projected(server_id=server_id, row=row)

    assert MCPProxySession._is_db_tool_enabled(tool) is offered


def test_the_projection_keeps_the_name_an_admin_gave_a_tool() -> None:
    # Kills the mutant that rebuilds a tool without the admin's display name:
    # the proxy titles a tool by it, and chat showed the server's own title.
    server_id = uuid4()
    row = _row(
        server_id,
        title="lookup_case_v2",
        display_name="Slå upp ärende",
        description="Reads a case.",
        input_schema=_SCHEMA,
        requires_approval=False,
        removed_from_remote=False,
    )

    assert _projected(server_id=server_id, row=row).display_name == "Slå upp ärende"
