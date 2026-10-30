"""Assistants that use the space's MCP servers, and apps, added to a space as
its editors add them, so a test can grow a space's applications."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID, uuid4

from httpx import AsyncClient

from eneo.database.tables.assistant_table import (
    AssistantMCPServers,
    AssistantMCPServerTools,
)
from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    SpacesMCPServers,
)

Headers = Mapping[str, str]


@dataclass(frozen=True)
class SpaceMCPServer:
    id: UUID
    tool_ids: tuple[UUID, ...]


async def space_mcp_servers(
    db_container, *, tenant_id: UUID, space_id: UUID, tools: Sequence[Sequence[str]]
) -> list[SpaceMCPServer]:
    """MCP servers linked to the space, one per entry of ``tools`` with the
    tools it names, each on for everyone and the space until switched off."""
    servers: list[SpaceMCPServer] = []
    async with db_container() as container:
        session = container.session()
        for names in tools:
            server = MCPServers(
                tenant_id=tenant_id,
                name=f"mcp-{uuid4().hex[:8]}",
                http_url="https://mcp.example.test/mcp",
                http_auth_type="none",
                is_enabled=True,
            )
            session.add(server)
            await session.flush()
            session.add(SpacesMCPServers(space_id=space_id, mcp_server_id=server.id))
            rows = [
                MCPServerTools(mcp_server_id=server.id, name=name) for name in names
            ]
            session.add_all(rows)
            await session.flush()
            servers.append(SpaceMCPServer(server.id, tuple(row.id for row in rows)))
    return servers


async def assistant_using(
    client: AsyncClient,
    headers: Headers,
    db_container,
    *,
    space_id: UUID,
    servers: Sequence[UUID],
    switched_on: Mapping[UUID, bool],
) -> UUID:
    """An assistant of the space using ``servers``, with its own switch for
    each tool in ``switched_on``."""
    response = await client.post(
        "/api/v1/assistants/",
        json={"name": f"Assistent {uuid4().hex[:6]}", "space_id": str(space_id)},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assistant_id = UUID(response.json()["id"])
    async with db_container() as container:
        session = container.session()
        session.add_all(
            [
                *(
                    AssistantMCPServers(assistant_id=assistant_id, mcp_server_id=id_)
                    for id_ in servers
                ),
                *(
                    AssistantMCPServerTools(
                        assistant_id=assistant_id,
                        mcp_server_tool_id=tool_id,
                        is_enabled=enabled,
                    )
                    for tool_id, enabled in switched_on.items()
                ),
            ]
        )
    return assistant_id


async def add_assistants(
    client: AsyncClient,
    headers: Headers,
    db_container,
    *,
    space_id: UUID,
    servers: Sequence[SpaceMCPServer],
    count: int,
) -> None:
    """``count`` assistants using every server, each with its first tool on."""
    for _ in range(count):
        await assistant_using(
            client,
            headers,
            db_container,
            space_id=space_id,
            servers=[server.id for server in servers],
            switched_on={server.tool_ids[0]: True for server in servers},
        )


async def add_apps(
    client: AsyncClient, headers: Headers, *, space_id: UUID, count: int
) -> None:
    """``count`` apps; the space must have a transcription model."""
    for _ in range(count):
        response = await client.post(
            f"/api/v1/spaces/{space_id}/applications/apps/",
            json={"name": f"App {uuid4().hex[:6]}"},
            headers=headers,
        )
        assert response.status_code == 201, response.text
