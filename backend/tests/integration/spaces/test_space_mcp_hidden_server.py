"""A save keeps a disabled MCP server, which the space hides, and the tool switches
the space hides."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    MCPServerToolSettings,
    SpacesMCPServers,
    SpacesMCPServerTools,
)
from tests.integration.spaces.test_space_mcp_audit import _headers

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _set_enabled(db_container, server_id: UUID, enabled: bool) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(MCPServers)
            .where(MCPServers.id == server_id)
            .values(is_enabled=enabled)
        )


async def _switch_off_for_everyone(
    db_container, tenant_id: UUID, tool_id: UUID
) -> None:
    async with db_container() as container:
        await container.session().execute(
            insert(MCPServerToolSettings)
            .values(tenant_id=tenant_id, mcp_server_tool_id=tool_id, is_enabled=False)
            .on_conflict_do_update(
                index_elements=["tenant_id", "mcp_server_tool_id"],
                set_={"is_enabled": False},
            )
        )


async def _stored(db_container, space_id: UUID) -> tuple[set[UUID], dict[UUID, bool]]:
    """The space's stored server links and tool switches."""
    async with db_container() as container:
        session = container.session()
        links = set(
            await session.scalars(
                sa.select(SpacesMCPServers.mcp_server_id).where(
                    SpacesMCPServers.space_id == space_id
                )
            )
        )
        rows = await session.execute(
            sa.select(
                SpacesMCPServerTools.mcp_server_tool_id,
                SpacesMCPServerTools.is_enabled,
            ).where(SpacesMCPServerTools.space_id == space_id)
        )
        return links, {tool_id: is_enabled for tool_id, is_enabled in rows.all()}


async def test_adding_a_server_keeps_a_disabled_server_and_its_tool_switch(
    client, db_container, admin_user, patch_auth_service_jwt
):
    """Kills: the MCP server list edit replaces every stored link (the disabled
    server is unlinked); the tool switch edit replaces every stored switch (the
    disabled server's tool comes back on after it is enabled again); the switch
    edit is scoped to no shown tools, or to the tools of the selected servers
    read after ``Space.update`` (an empty list then clears nothing); the shown
    tools include one the instance admin switched off for everyone (the space's
    own switch-off of it is lost, so it is on again once the admin re-enables
    it)."""
    headers = await _headers(db_container, admin_user)
    servers: dict[str, tuple[UUID, UUID]] = {}
    async with db_container() as container:
        session = container.session()
        for name in ("shown", "hidden", "added"):
            server = MCPServers(
                tenant_id=admin_user.tenant_id,
                name=f"{name}-{uuid4().hex[:6]}",
                http_url="https://hidden-server.example.test/mcp",
                http_auth_type="none",
                is_enabled=True,
            )
            session.add(server)
            await session.flush()
            tool = MCPServerTools(mcp_server_id=server.id, name=f"tool_{name}")
            session.add(tool)
            await session.flush()
            servers[name] = (server.id, tool.id)
        admin_off_tool = MCPServerTools(
            mcp_server_id=servers["shown"][0], name="tool_admin_off"
        )
        session.add(admin_off_tool)
        await session.flush()
        admin_off = admin_off_tool.id
    (shown, shown_tool), (hidden, hidden_tool), (added, added_tool) = (
        servers["shown"],
        servers["hidden"],
        servers["added"],
    )
    response = await client.post(
        "/api/v1/spaces/", json={"name": f"hidden-{uuid4().hex[:8]}"}, headers=headers
    )
    assert response.status_code == 201, response.text
    space_id = UUID(response.json()["id"])
    url = f"/api/v1/spaces/{space_id}/"
    response = await client.patch(
        url,
        json={
            "mcp_servers": [{"id": str(shown)}, {"id": str(hidden)}],
            "mcp_tools": [
                {"tool_id": str(shown_tool), "is_enabled": True},
                {"tool_id": str(hidden_tool), "is_enabled": False},
                {"tool_id": str(admin_off), "is_enabled": False},
            ],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    await _set_enabled(db_container, hidden, False)
    await _switch_off_for_everyone(db_container, admin_user.tenant_id, admin_off)

    # The settings page adds a server with the servers and tool switches the
    # space shows, plus the new server's tools (SelectMCPServers.toggleServer).
    listed = (await client.get(url, headers=headers)).json()["mcp_servers"]
    assert [server["id"] for server in listed] == [str(shown)]
    response = await client.patch(
        url,
        json={
            "mcp_servers": [{"id": str(shown)}, {"id": str(added)}],
            "mcp_tools": [
                {"tool_id": tool["id"], "is_enabled": tool["is_enabled"]}
                for server in listed
                for tool in server["tools"]
            ]
            + [{"tool_id": str(added_tool), "is_enabled": True}],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text

    assert await _stored(db_container, space_id) == (
        {shown, hidden, added},
        {shown_tool: True, hidden_tool: False, admin_off: False, added_tool: True},
    )

    # An empty switch list clears the switches the space shows, and only those.
    response = await client.patch(
        url,
        json={"mcp_servers": [{"id": str(shown)}, {"id": str(added)}], "mcp_tools": []},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert await _stored(db_container, space_id) == (
        {shown, hidden, added},
        {hidden_tool: False, admin_off: False},
    )
