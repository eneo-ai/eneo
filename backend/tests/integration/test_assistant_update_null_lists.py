"""A null list on an assistant update keeps what is stored, as on develop.

POST /api/v1/assistants/{id}/ treated null for groups, websites, attachments,
MCP servers and the other list fields as an empty list, so an API caller that
sent null wiped them. Develop treats null like an omitted field: nothing
changes. Only an explicit [] clears a list.

Stored groups, websites and MCP servers are checked here against the database;
attachments cannot be seeded without the file storage pipeline, and every list
field is covered at the request mapping in test_assistant_update.py."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.assistant_table import (
    AssistantMCPServers,
    AssistantsGroups,
    AssistantsWebsites,
)
from eneo.database.tables.mcp_server_table import MCPServers, SpacesMCPServers
from eneo.database.tables.spaces_table import SpacesEmbeddingModels
from eneo.database.tables.websites_table import Websites
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserUpdate

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# (API field, association table, association column)
FIELDS = {
    "groups": (AssistantsGroups, AssistantsGroups.group_id),
    "websites": (AssistantsWebsites, AssistantsWebsites.website_id),
    "mcp_servers": (AssistantMCPServers, AssistantMCPServers.mcp_server_id),
}


@dataclass(frozen=True)
class Stored:
    headers: dict[str, str]
    assistant_id: UUID
    linked: dict[str, UUID]


async def _token(db_container, admin_user) -> str:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"null-lists-{uuid4().hex[:8]}",
                permissions=[
                    Permission.ASSISTANTS,
                    Permission.COLLECTIONS,
                    Permission.WEBSITES,
                    Permission.SHARED_SPACES,
                    Permission.ADMIN,
                ],
                tenant_id=admin_user.tenant_id,
            )
        )
    async with db_container() as container:
        admin = await container.user_repo().update(
            UserUpdate(id=admin_user.id, roles=[ModelId(id=role.id)])
        )
        assert admin is not None
        return container.auth_service().create_access_token_for_user(admin)


async def _linked(db_container, assistant_id: UUID) -> dict[str, set[UUID]]:
    async with db_container() as container:
        session = container.session()
        linked: dict[str, set[UUID]] = {}
        for field, (table, column) in FIELDS.items():
            rows = await session.scalars(
                sa.select(column).where(table.assistant_id == assistant_id)
            )
            linked[field] = set(rows.all())
        return linked


@pytest.fixture
async def stored(client, db_container, admin_user, patch_auth_service_jwt) -> Stored:
    headers = {"Authorization": f"Bearer {await _token(db_container, admin_user)}"}
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"null-lists-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    space_id = UUID(response.json()["id"])
    response = await client.post(
        f"/api/v1/spaces/{space_id}/knowledge/groups/",
        json={"name": f"group-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    group_id = UUID(response.json()["id"])
    response = await client.post(
        f"/api/v1/spaces/{space_id}/applications/assistants/",
        json={"name": "keeps its lists"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assistant_id = UUID(response.json()["id"])

    async with db_container() as container:
        session = container.session()
        embedding_model_id = await session.scalar(
            sa.select(SpacesEmbeddingModels.embedding_model_id).where(
                SpacesEmbeddingModels.space_id == space_id
            )
        )
        assert embedding_model_id is not None
        website = Websites(
            name="Kommunen",
            url=f"https://example.invalid/{uuid4().hex[:8]}",
            download_files=False,
            crawl_type="crawl",
            update_interval="never",
            size=0,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            space_id=space_id,
        )
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"null-lists-{uuid4().hex[:8]}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
        )
        session.add_all([website, server])
        await session.flush()
        session.add(SpacesMCPServers(space_id=space_id, mcp_server_id=server.id))
        linked = {
            "groups": group_id,
            "websites": website.id,
            "mcp_servers": server.id,
        }
        for field, (table, column) in FIELDS.items():
            session.add(table(assistant_id=assistant_id, **{column.key: linked[field]}))
        await session.flush()

    assert await _linked(db_container, assistant_id) == {
        field: {value} for field, value in linked.items()
    }
    return Stored(headers=headers, assistant_id=assistant_id, linked=linked)


async def _update(client, stored: Stored, body: dict[str, object]) -> None:
    response = await client.post(
        f"/api/v1/assistants/{stored.assistant_id}/", json=body, headers=stored.headers
    )
    assert response.status_code == 200, (body, response.text)


async def test_null_lists_keep_what_is_stored(client, db_container, stored: Stored):
    await _update(
        client,
        stored,
        {
            "name": "null everywhere",
            "groups": None,
            "websites": None,
            "attachments": None,
            "mcp_servers": None,
            "mcp_tools": None,
            "integration_knowledge_list": None,
            "enabled_capabilities": None,
            "skill_bindings": None,
        },
    )

    assert await _linked(db_container, stored.assistant_id) == {
        field: {value} for field, value in stored.linked.items()
    }


async def test_absent_lists_keep_what_is_stored(client, db_container, stored: Stored):
    await _update(client, stored, {"name": "nothing about lists"})

    assert await _linked(db_container, stored.assistant_id) == {
        field: {value} for field, value in stored.linked.items()
    }


@pytest.mark.parametrize("field", list(FIELDS))
async def test_an_empty_list_clears_only_that_list(
    client, db_container, stored: Stored, field: str
):
    await _update(client, stored, {field: []})

    expected = {name: {value} for name, value in stored.linked.items()}
    expected[field] = set()
    assert await _linked(db_container, stored.assistant_id) == expected


@pytest.mark.parametrize("field", list(FIELDS))
async def test_a_null_list_next_to_other_changes_keeps_that_list(
    client, db_container, stored: Stored, field: str
):
    await _update(client, stored, {"description": "changed", field: None})

    assert await _linked(db_container, stored.assistant_id) == {
        name: {value} for name, value in stored.linked.items()
    }
