"""Flow discovery: `GET /api/v1/flows/` without `space_id`.

A runner, such as a module acting for a signed-in user, lists the flows of every
space that user belongs to, narrowed by the credential it calls with.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from eneo.database.tables.spaces_table import Spaces, SpacesUserGroups, SpacesUsers
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import usergroups_users_table, users_roles_table
from eneo.flows.domain.flow import Flow
from eneo.flows.published_definition import build_published_definition_json
from eneo.main.container.container import Container
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from tests.integration.module_session_support import (
    enable_module,
    install_module,
    module_login,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# What the reader sees without `published_only`: everything in spaces where
# they edit flows (directly, through the group, or as the personal space's
# owner), only the published flow where they view.
VISIBLE = (
    "editor.published",
    "editor.draft",
    "viewer.published",
    "group.published",
    "group.draft",
    "both.published",
    "both.draft",
    "personal.published",
    "personal.draft",
)
VISIBLE_PUBLISHED = tuple(label for label in VISIBLE if label.endswith(".published"))


@dataclass(frozen=True)
class World:
    admin_token: str
    reader_id: UUID
    reader_token: str
    group_id: UUID
    org_space_id: UUID
    editor_space_id: UUID
    stranger_space_id: UUID
    flow_ids: dict[str, str]
    space_names: dict[str, str]

    @property
    def reader_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.reader_token}"}

    def ids(self, labels: tuple[str, ...]) -> set[str]:
        return {self.flow_ids[label] for label in labels}


async def _flow(
    container: Container, *, space_id: UUID, name: str, published: bool
) -> str:
    user = container.user()
    flow_repo = container.flow_repo()
    flow = await flow_repo.create(
        Flow(
            tenant_id=user.tenant_id,
            space_id=space_id,
            name=name,
            created_by_user_id=user.id,
            owner_user_id=user.id,
        ),
        tenant_id=user.tenant_id,
    )
    flow_id = flow.require_persisted_id()
    if published:
        await container.flow_version_repo().create(
            flow_id=flow_id,
            version=1,
            definition_json=build_published_definition_json(
                flow_id=flow_id,
                name=name,
                description=None,
                metadata_json=None,
                steps=[],
            ),
            tenant_id=user.tenant_id,
        )
        await flow_repo.update(
            flow.model_copy(update={"published_version": 1}),
            tenant_id=user.tenant_id,
        )
    return str(flow_id)


async def _space_with_flows(
    container: Container,
    *,
    label: str,
    name: str,
    tenant_space_id: UUID,
    flow_ids: dict[str, str],
    space_names: dict[str, str],
    owner_id: UUID | None = None,
    drafts: bool = True,
) -> UUID:
    session = container.session()
    space = Spaces(
        name=name,
        tenant_id=container.user().tenant_id,
        tenant_space_id=tenant_space_id,
        user_id=owner_id,
    )
    session.add(space)
    await session.flush()
    for kind in ("published", "draft") if drafts else ("published",):
        flow_ids[f"{label}.{kind}"] = await _flow(
            container,
            space_id=space.id,
            name=f"{name} {kind}",
            published=kind == "published",
        )
        space_names[f"{label}.{kind}"] = name
    return space.id


@pytest.fixture
async def world(
    db_container, flow_process_auth_headers, admin_user, user_factory
) -> World:
    async with db_container() as container:
        session = container.session()
        tenant_id = admin_user.tenant_id
        reader = await user_factory(session)
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"flow-reader-{uuid4().hex[:8]}",
                permissions=[Permission.FLOWS_VIEW],
                tenant_id=tenant_id,
            )
        )
        await session.execute(
            sa.insert(users_roles_table).values(user_id=reader.id, role_id=role.id)
        )
        group = UserGroups(name=f"flow-readers-{uuid4().hex[:8]}", tenant_id=tenant_id)
        session.add(group)
        await session.flush()
        await session.execute(
            sa.insert(usergroups_users_table).values(
                user_id=reader.id, user_group_id=group.id
            )
        )
        org = (
            await session.scalars(
                sa.select(Spaces).where(
                    Spaces.tenant_id == tenant_id,
                    Spaces.user_id.is_(None),
                    Spaces.tenant_space_id.is_(None),
                )
            )
        ).one()
        # The organization space shows flows to its admins only.
        session.add(SpacesUsers(space_id=org.id, user_id=reader.id, role="editor"))
        flow_ids: dict[str, str] = {
            "org.published": await _flow(
                container, space_id=org.id, name="Org published", published=True
            )
        }
        space_names: dict[str, str] = {"org.published": org.name}

        async def space(
            label: str, name: str, *, owner_id: UUID | None = None, drafts: bool = True
        ) -> UUID:
            return await _space_with_flows(
                container,
                label=label,
                name=name,
                tenant_space_id=org.id,
                flow_ids=flow_ids,
                space_names=space_names,
                owner_id=owner_id,
                drafts=drafts,
            )

        editor_space_id = await space("editor", "Ekonomi")
        viewer_space_id = await space("viewer", "HR")
        group_space_id = await space("group", "Socialtjänst")
        both_space_id = await space("both", "Skola")
        await space("personal", "Min yta", owner_id=reader.id)
        stranger_space_id = await space("stranger", "Bygg", drafts=False)
        session.add_all(
            [
                SpacesUsers(space_id=editor_space_id, user_id=reader.id, role="editor"),
                SpacesUsers(space_id=viewer_space_id, user_id=reader.id, role="viewer"),
                SpacesUserGroups(
                    space_id=group_space_id, user_group_id=group.id, role="editor"
                ),
                # Reached twice: the group's editor role outranks the direct viewer.
                SpacesUsers(space_id=both_space_id, user_id=reader.id, role="viewer"),
                SpacesUserGroups(
                    space_id=both_space_id, user_group_id=group.id, role="editor"
                ),
                # Space-scoped keys are created by an admin of that space.
                SpacesUsers(
                    space_id=editor_space_id, user_id=admin_user.id, role="admin"
                ),
                SpacesUsers(
                    space_id=stranger_space_id, user_id=admin_user.id, role="admin"
                ),
            ]
        )
        await session.flush()
        reader_in_db = await container.user_repo().get_user_by_id(reader.id)
        return World(
            admin_token=flow_process_auth_headers.token,
            reader_id=reader.id,
            reader_token=container.auth_service().create_access_token_for_user(
                reader_in_db
            ),
            group_id=group.id,
            org_space_id=org.id,
            editor_space_id=editor_space_id,
            stranger_space_id=stranger_space_id,
            flow_ids=flow_ids,
            space_names=space_names,
        )


async def _page(
    client: AsyncClient, headers: Mapping[str, str], **params: object
) -> dict[str, Any]:
    response = await client.get("/api/v1/flows/", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _discover(
    client: AsyncClient, headers: Mapping[str, str], **params: object
) -> list[dict[str, Any]]:
    page = await _page(client, headers, limit=200, **params)
    assert page["has_more"] is False
    return page["items"]


def _ids(items: list[dict[str, Any]]) -> set[str]:
    return {str(item["id"]) for item in items}


async def test_a_user_discovers_the_flows_of_every_space_they_belong_to(
    client: AsyncClient, world: World
):
    items = await _discover(client, world.reader_headers)

    assert _ids(items) == world.ids(VISIBLE)
    assert len(items) == len(VISIBLE)
    assert {str(item["id"]): item["space_name"] for item in items} == {
        world.flow_ids[label]: world.space_names[label] for label in VISIBLE
    }
    order = [(str(item["created_at"]), str(item["id"])) for item in items]
    assert order == sorted(order)


async def test_published_only_hides_drafts_even_where_the_user_edits(
    client: AsyncClient, world: World
):
    items = await _discover(client, world.reader_headers, published_only=True)

    assert _ids(items) == world.ids(VISIBLE_PUBLISHED)
    assert all(item["published_version"] == 1 for item in items)


async def test_the_organization_space_lists_flows_to_its_admins(
    client: AsyncClient, world: World, db_container
):
    async with db_container() as container:
        await container.session().execute(
            sa.update(SpacesUsers)
            .where(
                SpacesUsers.space_id == world.org_space_id,
                SpacesUsers.user_id == world.reader_id,
            )
            .values(role="admin")
        )

    items = await _discover(client, world.reader_headers)

    assert _ids(items) == world.ids((*VISIBLE, "org.published"))


async def test_pages_across_spaces_in_one_order_without_repeats(
    client: AsyncClient, world: World
):
    everything = await _discover(client, world.reader_headers)
    pages = [
        await _page(client, world.reader_headers, limit=4, offset=offset)
        for offset in (0, 4, 8)
    ]

    assert [page["has_more"] for page in pages] == [True, True, False]
    assert [page["count"] for page in pages] == [4, 4, 1]
    paged = [item for page in pages for item in page["items"]]
    assert [item["id"] for item in paged] == [item["id"] for item in everything]


async def test_a_service_key_must_name_the_space_it_lists(
    client: AsyncClient, world: World
):
    created = await client.post(
        "/api/v1/api-keys",
        json={
            "name": f"flow-discovery-{uuid4().hex[:8]}",
            "key_type": "sk_",
            "permission": "write",
            "scope_type": "tenant",
            "ownership": "service",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "resource_permissions": {"flows": "write"},
        },
        headers={"Authorization": f"Bearer {world.admin_token}"},
    )
    assert created.status_code == 201, created.text
    headers = {"X-API-Key": created.json()["secret"]}

    refused = await client.get("/api/v1/flows/", headers=headers)
    assert refused.status_code == 400, refused.text
    assert refused.json()["code"] == "flow_service_key_space_id_required"

    items = await _discover(client, headers, space_id=world.editor_space_id)
    assert _ids(items) == world.ids(("editor.published",))
    assert items[0]["space_name"] == "Ekonomi"


async def test_a_module_session_discovers_within_its_key_scope(
    client: AsyncClient, world: World, db_container, admin_user
):
    async def module_headers(space_id: UUID | None) -> dict[str, str]:
        module_key = await enable_module(db_container, tenant_id=admin_user.tenant_id)
        secret = await install_module(
            client,
            admin_token=world.admin_token,
            module_key=module_key,
            space_id=space_id,
        )
        module_token = await module_login(
            client,
            service_key=secret,
            user_token=world.reader_token,
            module_key=module_key,
        )
        return {"X-API-Key": secret, "Authorization": f"Bearer {module_token}"}

    scoped = await module_headers(world.editor_space_id)
    tenant_wide = await module_headers(None)
    stranger_scoped = await module_headers(world.stranger_space_id)

    assert _ids(await _discover(client, scoped, published_only=True)) == world.ids(
        ("editor.published",)
    )
    assert _ids(await _discover(client, tenant_wide, published_only=True)) == world.ids(
        VISIBLE_PUBLISHED
    )
    # The key reaches a space the human is not a member of: nothing to discover.
    assert await _discover(client, stranger_scoped) == []


async def test_discovery_query_count_does_not_grow_with_spaces_or_flows(
    client: AsyncClient, world: World, db_container
):
    async def discovery_selects() -> tuple[int, list[str]]:
        async with db_container() as container:
            bind = container.session().get_bind()
            engine = getattr(bind, "engine", bind)
            statements: list[str] = []

            def record(_conn, _cursor, statement, _params, _context, _many) -> None:
                if statement.lstrip().upper().startswith("SELECT"):
                    statements.append(statement.lower())

            sa.event.listen(engine, "before_cursor_execute", record)
            try:
                items = await _discover(client, world.reader_headers)
            finally:
                sa.event.remove(engine, "before_cursor_execute", record)
        return len(items), statements

    first_count, first = await discovery_selects()
    async with db_container() as container:
        flow_ids: dict[str, str] = {}
        for name in ("Kultur", "Miljö"):
            space_id = await _space_with_flows(
                container,
                label=name,
                name=name,
                tenant_space_id=world.org_space_id,
                flow_ids=flow_ids,
                space_names={},
            )
            container.session().add_all(
                [
                    SpacesUsers(
                        space_id=space_id, user_id=world.reader_id, role="editor"
                    ),
                    SpacesUserGroups(
                        space_id=space_id, user_group_id=world.group_id, role="viewer"
                    ),
                ]
            )
    second_count, second = await discovery_selects()

    assert second_count == first_count + 4
    assert len(second) == len(first)
    # Space hydration loads model mappings; discovery reads membership facts only.
    assert not any("spaces_completion_models" in statement for statement in second)
