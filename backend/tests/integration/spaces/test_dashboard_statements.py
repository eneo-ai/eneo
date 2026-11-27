"""The dashboard reads the applications of all the caller's spaces together:
its statement count does not grow with the number of spaces, and every space
still gets its own applications, prompts, attachments and MCP tools."""

from __future__ import annotations

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
    SpacesMCPServers,
    SpacesMCPServerTools,
)
from tests.integration.flows.statement_capture_support import capture_queries

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@dataclass(frozen=True)
class SeededSpace:
    id: UUID
    assistant_id: UUID
    app_id: UUID
    group_chat_id: UUID
    file_id: UUID
    fetch_on: bool


@dataclass(frozen=True)
class SharedServer:
    id: UUID
    fetch: UUID
    search: UUID


@pytest.fixture
async def headers(
    db_container, admin_user, patch_auth_service_jwt, transcription_model_factory
) -> dict[str, str]:
    _ = patch_auth_service_jwt
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
        # Apps can only be created in a space with a transcription model.
        await transcription_model_factory(
            container.session(), "fixture-whisper", is_default=True
        )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def server(db_container, admin_user) -> SharedServer:
    """One MCP server every seeded space uses, with two tools."""
    async with db_container() as container:
        session = container.session()
        row = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"mcp-{uuid4().hex[:8]}",
            http_url="https://mcp.example.test/mcp",
            http_auth_type="none",
            is_enabled=True,
        )
        session.add(row)
        await session.flush()
        fetch = MCPServerTools(mcp_server_id=row.id, name="fetch")
        search = MCPServerTools(mcp_server_id=row.id, name="search")
        session.add_all([fetch, search])
        await session.flush()
        return SharedServer(row.id, fetch.id, search.id)


async def _add_space(
    client, headers, db_container, server: SharedServer, *, fetch_on: bool
) -> SeededSpace:
    """A space with an assistant and an app, each with its own prompt and the
    space's own attachment, and a group chat. The assistant switches both
    tools of the shared server on; the space switches ``fetch`` off unless
    ``fetch_on``."""
    created = await client.post(
        "/api/v1/spaces/", json={"name": f"dash-{uuid4().hex[:8]}"}, headers=headers
    )
    assert created.status_code == 201, created.text
    space_id = UUID(created.json()["id"])
    upload = await client.post(
        "/api/v1/files/",
        files={"upload_file": (f"{space_id}.txt", b"policy", "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    file_id = UUID(upload.json()["id"])
    attachments = [{"id": str(file_id)}]

    assistant = await client.post(
        "/api/v1/assistants/",
        json={"name": f"a-{uuid4().hex[:6]}", "space_id": str(space_id)},
        headers=headers,
    )
    assert assistant.status_code == 200, assistant.text
    assistant_id = UUID(assistant.json()["id"])
    updated = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"attachments": attachments, "prompt": {"text": f"assistant {space_id}"}},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text

    app = await client.post(
        f"/api/v1/spaces/{space_id}/applications/apps/",
        json={"name": f"app-{uuid4().hex[:6]}"},
        headers=headers,
    )
    assert app.status_code == 201, app.text
    app_id = UUID(app.json()["id"])
    updated = await client.patch(
        f"/api/v1/apps/{app_id}/",
        json={"attachments": attachments, "prompt": {"text": f"app {space_id}"}},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text

    group_chat = await client.post(
        f"/api/v1/spaces/{space_id}/applications/group-chats/",
        json={"name": f"gc-{uuid4().hex[:6]}"},
        headers=headers,
    )
    assert group_chat.status_code in (200, 201), group_chat.text

    async with db_container() as container:
        session = container.session()
        # A new space may already offer the tenant's enabled servers.
        await session.execute(
            insert(SpacesMCPServers)
            .values(space_id=space_id, mcp_server_id=server.id)
            .on_conflict_do_nothing()
        )
        session.add_all(
            [
                AssistantMCPServers(assistant_id=assistant_id, mcp_server_id=server.id),
                *(
                    AssistantMCPServerTools(
                        assistant_id=assistant_id,
                        mcp_server_tool_id=tool_id,
                        is_enabled=True,
                    )
                    for tool_id in (server.fetch, server.search)
                ),
                *(
                    []
                    if fetch_on
                    else [
                        SpacesMCPServerTools(
                            space_id=space_id,
                            mcp_server_tool_id=server.fetch,
                            is_enabled=False,
                        )
                    ]
                ),
            ]
        )
    return SeededSpace(
        id=space_id,
        assistant_id=assistant_id,
        app_id=app_id,
        group_chat_id=UUID(group_chat.json()["id"]),
        file_id=file_id,
        fetch_on=fetch_on,
    )


async def _dashboard(client, headers) -> tuple[int, dict[UUID, dict]]:
    """The dashboard's statement count and its spaces by id."""
    engine = sessionmanager._engine
    assert engine is not None
    await client.get("/api/v1/dashboard/", headers=headers)  # warms caches
    with capture_queries(engine.sync_engine) as statements:
        response = await client.get("/api/v1/dashboard/", headers=headers)
    assert response.status_code == 200, response.text
    spaces = response.json()["spaces"]["items"]
    return len(statements), {UUID(space["id"]): space for space in spaces}


def _ids(applications: dict, kind: str) -> list[UUID]:
    return [UUID(item["id"]) for item in applications[kind]["items"]]


async def test_dashboard_statements_do_not_grow_with_the_callers_spaces(
    client, db_container, headers, server
):
    seeded: list[SeededSpace] = []
    counts: list[int] = []
    dashboard: dict[UUID, dict] = {}
    for _ in range(2):
        for fetch_on in (True, False):
            seeded.append(
                await _add_space(
                    client, headers, db_container, server, fetch_on=fetch_on
                )
            )
        count, dashboard = await _dashboard(client, headers)
        counts.append(count)

    assert counts[1] == counts[0], counts

    for space in seeded:
        applications = dashboard[space.id]["applications"]
        assert _ids(applications, "assistants") == [space.assistant_id]
        assert _ids(applications, "apps") == [space.app_id]
        assert _ids(applications, "group_chats") == [space.group_chat_id]

    async with db_container() as container:
        spaces = {
            space.id: space
            for space in await container.space_repo().get_spaces_for_member(
                include_applications=True
            )
        }
    for space in seeded:
        loaded = spaces[space.id]
        (assistant,) = loaded.assistants
        (app,) = loaded.apps
        assert assistant.id == space.assistant_id
        assert assistant.prompt is not None
        assert assistant.prompt.text == f"assistant {space.id}"
        assert [file.id for file in assistant.attachments] == [space.file_id]
        assert {
            mcp_server.id: [(tool.name, tool.is_enabled) for tool in mcp_server.tools]
            for mcp_server in assistant.mcp_servers
        } == {
            server.id: [("fetch", True), ("search", True)]
            if space.fetch_on
            else [("search", True)]
        }
        assert app.id == space.app_id
        assert app.prompt is not None
        assert app.prompt.text == f"app {space.id}"
        assert [file.id for file in app.attachments] == [space.file_id]
        assert [chat.id for chat in loaded.group_chats] == [space.group_chat_id]
