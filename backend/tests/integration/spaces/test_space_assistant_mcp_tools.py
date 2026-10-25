"""A space load gives each assistant its MCP servers with the tools that are on
for the space, each switched as that assistant switched it, reading the tool
policy once for all assistants."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects.postgresql import insert

from eneo.database.database import sessionmanager
from eneo.database.tables.mcp_server_table import (
    MCPServerToolSettings,
    SpacesMCPServerTools,
)
from eneo.spaces.space import Space
from eneo.spaces.space_repo import SpaceRepository
from tests.integration.flows.statement_capture_support import capture_queries
from tests.integration.spaces.space_applications_support import (
    add_assistants,
    assistant_using,
    space_mcp_servers,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


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
            server.id: [
                (tool.name, tool.is_enabled_by_default) for tool in server.tools
            ]
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
            [tool.name for tool in server.tools if tool.is_enabled_by_default]
            == [server.tools[0].name]
            for assistant in space.assistants
            for server in assistant.mcp_servers
        )

    assert len(space.assistants) == 6
    assert counts[0] == counts[1], counts


async def test_assistants_with_their_own_servers_project_only_their_own_tools(
    client, db_container, admin_user, headers, monkeypatch
):
    space_id = await _space(client, headers)
    servers = await space_mcp_servers(
        db_container,
        tenant_id=admin_user.tenant_id,
        space_id=space_id,
        tools=[("a", "b", "c"), ("d", "e"), ("f", "g", "h", "i")],
    )
    first, second, third = servers
    async with db_container() as container:
        # Off for this space: projected, but never offered.
        container.session().add(
            SpacesMCPServerTools(
                space_id=space_id,
                mcp_server_tool_id=third.tool_ids[3],
                is_enabled=False,
            )
        )
    owners = {
        await assistant_using(
            client,
            headers,
            db_container,
            space_id=space_id,
            servers=[server.id],
            switched_on=dict.fromkeys(server.tool_ids[i::2], True),
        ): server
        for i, server in enumerate(servers)
    }

    # Count the tool rows the space load projects for its assistants.
    projected_rows: list[UUID] = []
    project = SpaceRepository._project_assistant_mcp_server_tools

    def counting_project(**kwargs):
        projected_rows.extend(tool.id for tool in kwargs["tools_db"])
        return project(**kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(
            SpaceRepository,
            "_project_assistant_mcp_server_tools",
            staticmethod(counting_project),
        )
        space = await _load(db_container, space_id)

    # Each assistant projects only its own server's rows, not every server's.
    assert sorted(projected_rows) == sorted(
        tool_id for server in servers for tool_id in server.tool_ids
    )
    assert _switches(space) == {
        assistant_id: {
            server.id: (
                [("a", True), ("b", False), ("c", True)]
                if server is first
                else [("d", False), ("e", True)]
                if server is second
                else [("f", False), ("g", False), ("h", True)]
            )
        }
        for assistant_id, server in owners.items()
    }
    async with db_container() as container:
        repo = container.space_repo()
        for assistant in space.assistants:
            untooled = deepcopy(assistant.mcp_servers)
            for server in untooled:
                server.tools = []
            assert assistant.mcp_servers == await repo.project_assistant_mcp_servers(
                space_id=space_id, assistant_id=assistant.id, mcp_servers=untooled
            )
