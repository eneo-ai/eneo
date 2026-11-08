"""A space load gives each assistant its MCP servers with the tools that are on
for the space, each switched as that assistant switched it, reading the tool
policy once for all assistants."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects.postgresql import insert

from eneo.database.database import sessionmanager
from eneo.database.tables.assistant_table import (
    AssistantMCPServers,
    AssistantMCPServerTools,
)
from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    MCPServerToolSettings,
    SpacesMCPServers,
    SpacesMCPServerTools,
)
from eneo.spaces.space import Space
from tests.integration.flows.statement_capture_support import capture_queries

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


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
    client,
    headers,
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
    client,
    headers,
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


@pytest.fixture
async def headers(db_container, admin_user, patch_auth_service_jwt) -> dict[str, str]:
    _ = patch_auth_service_jwt
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
    return {"Authorization": f"Bearer {token}"}


async def _space(client, headers) -> UUID:
    response = await client.post(
        "/api/v1/spaces/", json={"name": f"mcp-{uuid4().hex[:8]}"}, headers=headers
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def _load(db_container, space_id: UUID) -> Space:
    async with db_container() as container:
        return await container.space_repo().one(space_id)


def _switches(space: Space) -> dict[UUID, dict[UUID, list[tuple[str, bool]]]]:
    """Each assistant's servers, with each offered tool and its switch."""
    return {
        assistant.id: {
            server.id: [(tool.name, tool.is_enabled) for tool in server.tools]
            for server in assistant.mcp_servers
        }
        for assistant in space.assistants
    }


async def test_each_assistant_gets_its_own_switches_of_the_tools_on_for_the_space(
    client, db_container, admin_user, headers
):
    space_id = await _space(client, headers)
    first, second = await space_mcp_servers(
        db_container,
        tenant_id=admin_user.tenant_id,
        space_id=space_id,
        tools=[("a", "b", "c"), ("d", "e")],
    )
    a, b, c = first.tool_ids
    d, e = second.tool_ids
    async with db_container() as container:
        session = container.session()
        # Off for everyone, and off for this space: neither is offered.
        await session.execute(
            insert(MCPServerToolSettings).values(
                tenant_id=admin_user.tenant_id, mcp_server_tool_id=c, is_enabled=False
            )
        )
        session.add(
            SpacesMCPServerTools(
                space_id=space_id, mcp_server_tool_id=e, is_enabled=False
            )
        )
    both = await assistant_using(
        client,
        headers,
        db_container,
        space_id=space_id,
        servers=[first.id, second.id],
        switched_on={a: True, d: True},
    )
    only_first = await assistant_using(
        client,
        headers,
        db_container,
        space_id=space_id,
        servers=[first.id],
        switched_on={b: True, c: True, a: False},
    )
    only_second = await assistant_using(
        client,
        headers,
        db_container,
        space_id=space_id,
        servers=[second.id],
        switched_on={e: True},
    )

    space = await _load(db_container, space_id)

    assert _switches(space) == {
        both: {
            first.id: [("a", True), ("b", False)],
            second.id: [("d", True)],
        },
        only_first: {first.id: [("a", False), ("b", True)]},
        only_second: {second.id: [("d", False)]},
    }
    # Each assistant's servers, tools included, are what the one-assistant
    # projection gives it, and not what it gives another assistant.
    async with db_container() as container:
        repo = container.space_repo()
        for assistant in space.assistants:
            untooled = deepcopy(assistant.mcp_servers)
            for server in untooled:
                server.tools = []
            projected = await repo.project_assistant_mcp_servers(
                space_id=space_id,
                assistant_id=assistant.id,
                mcp_servers=deepcopy(untooled),
            )
            assert assistant.mcp_servers == projected
            other = only_first if assistant.id == both else both
            assert assistant.mcp_servers != await repo.project_assistant_mcp_servers(
                space_id=space_id, assistant_id=other, mcp_servers=untooled
            )


async def test_a_space_load_reads_the_tool_policy_once_for_all_assistants(
    client, db_container, admin_user, headers
):
    space_id = await _space(client, headers)
    servers = await space_mcp_servers(
        db_container,
        tenant_id=admin_user.tenant_id,
        space_id=space_id,
        tools=[("a", "b"), ("c", "d"), ("e",)],
    )
    engine = sessionmanager._engine
    assert engine is not None
    counts: list[int] = []
    for _ in range(2):
        await add_assistants(
            client, headers, db_container, space_id=space_id, servers=servers, count=3
        )
        await _load(db_container, space_id)  # warms per-process caches
        with capture_queries(engine.sync_engine) as statements:
            space = await _load(db_container, space_id)
        counts.append(len(statements))
        assert all(
            [tool.name for tool in server.tools if tool.is_enabled]
            == [server.tools[0].name]
            for assistant in space.assistants
            for server in assistant.mcp_servers
        )

    assert len(space.assistants) == 6
    assert counts[0] == counts[1], counts
