"""The narrow space reads behind permission decisions and polled or admin
views: a decision on a space loaded without the space's MCP catalog, the
caller's access facts and the ids of the integration knowledge a space shows."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import ORMExecuteState

from eneo.actors.actors.space_actor import SpaceActor
from eneo.authentication.auth_models import (
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
)
from eneo.database.tables.app_table import Apps
from eneo.database.tables.assistant_table import AssistantMCPServers, Assistants
from eneo.database.tables.integration_knowledge_spaces_table import (
    IntegrationKnowledgesSpaces,
)
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    SpacesMCPServers,
)
from eneo.database.tables.spaces_table import Spaces, SpacesUserGroups, SpacesUsers
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import usergroups_users_table
from eneo.main.exceptions import NotFoundException, UnauthorizedException
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.spaces.utils.space_utils import effective_space_ids_for
from eneo.tenants.tenant import TenantInDB
from eneo.user_groups.user_group import UserGroupState
from eneo.users.user import UserGroupInDBRead, UserInDB

_Decision = tuple[object, ...]


def _reads_mcp_catalog(sql: str) -> bool:
    """A statement reads an MCP tool, or an MCP server that is not one an
    assistant of the space attaches (the space's server options and the
    capability providers). An assistant's own tool switches
    (assistant_mcp_server_tools) are part of the assistant, not the catalog."""
    return re.search(r"\bmcp_server_tools\b", sql) is not None or (
        re.search(r"\bmcp_servers\b", sql) is not None
        and "assistant_mcp_servers" not in sql
    )


def _decision(actor: SpaceActor) -> _Decision:
    return (actor.can_read_space(), actor.can_read_flows(), actor.can_edit_flows())


async def _decided(load: Callable[[], Awaitable[SpaceActor]]) -> _Decision:
    try:
        return _decision(await load())
    except UnauthorizedException as refused:
        return (403, refused.code)
    except NotFoundException:
        return (404,)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("editor", (True, True, True)),
        ("viewer", (True, True, False)),
        ("outsider", (403, "forbidden_action")),
        ("group-editor-in-the-loaded-user-only", (True, True, True)),
        ("unknown-space", (404,)),
    ],
)
async def test_the_access_facts_decide_as_the_loaded_space(
    db_container,
    user_factory,
    completion_model_factory,
    assistant_factory,
    case: str,
    expected: _Decision,
) -> None:
    """Kills the mutants of the load a flow's access check uses instead of
    the whole space: one that answers another refusal than get_space's 403
    forbidden_action, takes group roles from the stored memberships instead
    of the loaded user's (as read_space_access_facts does), or still reads
    the MCP catalog: the space's server options with their tools (here an
    activated server with a tool), an assistant's servers' tools (the same
    server, attached to an assistant of the space) or the capability
    providers."""
    async with db_container() as container:
        session = container.session()
        admin = container.user()
        org_id = await session.scalar(
            sa.select(Spaces.id).where(
                Spaces.tenant_id == admin.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        space = Spaces(
            name=f"access-facts-{uuid4().hex[:6]}",
            tenant_id=admin.tenant_id,
            tenant_space_id=org_id,
        )
        server = MCPServers(
            tenant_id=admin.tenant_id,
            name=f"access-facts-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
        )
        group = UserGroups(
            name=f"access-facts-{uuid4().hex[:6]}", tenant_id=admin.tenant_id
        )
        caller = await user_factory(session)
        flows_role = await container.role_repo().create_role(
            RoleCreate(
                name=f"access-facts-{uuid4().hex[:8]}",
                permissions=[Permission.FLOWS],
                tenant_id=admin.tenant_id,
            )
        )
        session.add_all([space, server, group])
        await session.flush()
        await session.execute(
            sa.text("INSERT INTO users_roles (user_id, role_id) VALUES (:u, :r)"),
            {"u": caller.id, "r": flows_role.id},
        )
        model = await completion_model_factory(
            session, f"access-facts-{uuid4().hex[:6]}"
        )
        assistant = await assistant_factory(
            session, "Access facts", model.id, space_id=space.id
        )
        session.add_all(
            [
                SpacesMCPServers(space_id=space.id, mcp_server_id=server.id),
                MCPServerTools(mcp_server_id=server.id, name="lookup_case"),
                AssistantMCPServers(assistant_id=assistant.id, mcp_server_id=server.id),
            ]
        )
        if case in ("editor", "viewer"):
            session.add(SpacesUsers(space_id=space.id, user_id=caller.id, role=case))
        if case == "group-editor-in-the-loaded-user-only":
            await session.execute(
                sa.insert(usergroups_users_table).values(
                    user_id=caller.id, user_group_id=group.id
                )
            )
            session.add(
                SpacesUserGroups(
                    space_id=space.id, user_group_id=group.id, role="editor"
                )
            )
        await session.flush()
        user: UserInDB = await container.user_repo().get_user_by_id(caller.id)
        # The membership ends after the caller was loaded: both loads judge
        # the caller as loaded with the request.
        await session.execute(
            sa.delete(usergroups_users_table).where(
                usergroups_users_table.c.user_id == caller.id
            )
        )
        space_id: UUID = uuid4() if case == "unknown-space" else space.id
        stored = (space.id, server.id, group.id)

    # Each load has a session of its own, the access load first, as a request
    # makes it: a session that loaded the whole space would hand the access
    # load the space it already holds, and hide the statements it runs.
    async def decide_with_statements(*, whole: bool) -> tuple[_Decision, list[str]]:
        async with db_container(user=user) as container:
            statements: list[str] = []

            def record(state: ORMExecuteState) -> None:
                statements.append(
                    str(state.statement.compile(dialect=postgresql.dialect()))
                )

            event.listen(container.session().sync_session, "do_orm_execute", record)
            space_service, actors = container.space_service(), container.actor_manager()

            async def whole_space() -> SpaceActor:
                return actors.get_space_actor_from_space(
                    await space_service.get_space(space_id)
                )

            async def access_facts() -> SpaceActor:
                return actors.get_space_actor(
                    await space_service.get_space_access_facts(space_id)
                )

            decision = await _decided(whole_space if whole else access_facts)
            return decision, statements

    try:
        new, statements = await decide_with_statements(whole=False)
        old, whole_statements = await decide_with_statements(whole=True)
        catalog_reads = sum(_reads_mcp_catalog(sql) for sql in whole_statements)
    finally:
        async with db_container() as container:
            session = container.session()
            await session.execute(
                sa.delete(MCPServers).where(MCPServers.id == stored[1])
            )
            await session.execute(sa.delete(Spaces).where(Spaces.id == stored[0]))
            await session.execute(
                sa.delete(UserGroups).where(UserGroups.id == stored[2])
            )

    assert (old, new) == (expected, expected)
    if case != "unknown-space":
        # The control: the whole space reads the catalog this case activated.
        assert catalog_reads > 0
    assert not any(_reads_mcp_catalog(sql) for sql in statements)


@dataclass
class Tenancy:
    """A fresh tenant, so its organization space holds only this test's rows."""

    tenant: TenantInDB
    tenant_id: UUID
    caller_id: UUID
    organization: UUID
    space: UUID
    other_space: UUID
    foreign_space: UUID
    group: UUID
    deleted_group: UUID

    def caller(self, admin_user: UserInDB, *group_ids: UUID) -> UserInDB:
        return admin_user.model_copy(
            update={
                "id": self.caller_id,
                "tenant_id": self.tenant_id,
                "tenant": self.tenant,
                "user_groups": [
                    UserGroupInDBRead(id=group_id, name=str(group_id))
                    for group_id in group_ids
                ],
            }
        )


async def _space(session, *, tenant_id: UUID, name: str, parent: UUID | None) -> UUID:
    space = Spaces(name=name, tenant_id=tenant_id, user_id=None, tenant_space_id=parent)
    session.add(space)
    await session.flush()
    return space.id


async def _group(session, *, tenant_id: UUID, state: str | None = None) -> UUID:
    group = UserGroups(name=f"group-{uuid4()}", tenant_id=tenant_id, state=state)
    session.add(group)
    await session.flush()
    return group.id


@pytest.fixture
async def tenancy(db_container, tenant_factory, user_factory) -> Tenancy:
    async with db_container() as container:
        session = container.session()
        tenant_id = (await tenant_factory(session)).id
        caller_id = (await user_factory(session, tenant_id=tenant_id)).id
        colleague_id = (await user_factory(session, tenant_id=tenant_id)).id
        organization = await _space(
            session, tenant_id=tenant_id, name="Org", parent=None
        )
        space = await _space(
            session, tenant_id=tenant_id, name="Barn", parent=organization
        )
        other_space = await _space(
            session, tenant_id=tenant_id, name="Ekonomi", parent=organization
        )
        foreign_tenant = await tenant_factory(session)
        foreign_space = await _space(
            session, tenant_id=foreign_tenant.id, name="Annan", parent=None
        )
        group = await _group(session, tenant_id=tenant_id)
        deleted_group = await _group(
            session, tenant_id=tenant_id, state=UserGroupState.DELETED.value
        )
        await session.execute(
            sa.insert(SpacesUsers),
            [
                dict(space_id=space, user_id=caller_id, role="viewer"),
                dict(space_id=space, user_id=colleague_id, role="admin"),
                dict(space_id=other_space, user_id=colleague_id, role="admin"),
                dict(space_id=foreign_space, user_id=caller_id, role="admin"),
            ],
        )
        await session.execute(
            sa.insert(SpacesUserGroups),
            [
                dict(space_id=space, user_group_id=group, role="editor"),
                dict(space_id=other_space, user_group_id=deleted_group, role="admin"),
            ],
        )
        tenant = await container.tenant_repo().get(tenant_id)
        assert tenant is not None
    return Tenancy(
        tenant=tenant,
        tenant_id=tenant_id,
        caller_id=caller_id,
        organization=organization,
        space=space,
        other_space=other_space,
        foreign_space=foreign_space,
        group=group,
        deleted_group=deleted_group,
    )


async def test_space_facts_hold_only_the_callers_memberships(
    db_container, admin_user, tenancy
):
    caller = tenancy.caller(admin_user, tenancy.group, tenancy.deleted_group)
    async with db_container(user=caller, tenant=tenancy.tenant) as container:
        repo = container.space_repo()
        facts = await repo.get_space_access_facts(tenancy.space)
        other = await repo.get_space_access_facts(tenancy.other_space)

    assert (facts.id, facts.tenant_id, facts.user_id, facts.tenant_space_id) == (
        tenancy.space,
        tenancy.tenant_id,
        None,
        tenancy.organization,
    )
    # The colleague's admin seat is not the caller's business.
    assert {id: fact.role for id, fact in facts.members.items()} == {
        tenancy.caller_id: "viewer"
    }
    assert {id: fact.role for id, fact in facts.group_members.items()} == {
        tenancy.group: "editor"
    }
    assert facts.default_assistant_id is None
    assert not facts.assistant_ids and not facts.app_ids
    # A deleted group grants nothing.
    assert not other.members and not other.group_members


async def test_space_facts_of_another_tenant_are_not_found(
    db_container, admin_user, tenancy
):
    # Even a space the caller's id holds a seat in.
    async with db_container(
        user=tenancy.caller(admin_user), tenant=tenancy.tenant
    ) as container:
        repo = container.space_repo()
        with pytest.raises(NotFoundException):
            await repo.get_space_access_facts(tenancy.foreign_space)
        with pytest.raises(NotFoundException):
            await repo.get_space_access_facts(uuid4())


async def test_facts_for_many_spaces_leave_out_other_tenants(
    db_container, admin_user, tenancy
):
    caller = tenancy.caller(admin_user, tenancy.group)
    async with db_container(user=caller, tenant=tenancy.tenant) as container:
        repo = container.space_repo()
        facts = await repo.get_spaces_access_facts(
            [tenancy.space, tenancy.other_space, tenancy.foreign_space, uuid4()]
        )
        single = await repo.get_space_access_facts(tenancy.space)
        assert await repo.get_spaces_access_facts([]) == {}

    assert set(facts) == {tenancy.space, tenancy.other_space}
    assert facts[tenancy.space] == single
    assert not facts[tenancy.other_space].members
    assert not facts[tenancy.other_space].group_members


async def test_visible_knowledge_ids_are_what_the_space_loader_shows(
    db_container,
    admin_user,
    tenancy,
    tenant_factory,
    user_integration_factory,
    embedding_model_factory,
):
    tenant_id = tenancy.tenant_id
    async with db_container() as container:
        session = container.session()
        model = await embedding_model_factory(session)
        connection = await user_integration_factory(session, tenant_id=tenant_id)
        foreign_tenant = await tenant_factory(session)
        foreign_connection = await user_integration_factory(
            session, tenant_id=foreign_tenant.id
        )

        async def knowledge(space_id: UUID, minutes: int, *, foreign=False) -> UUID:
            item = IntegrationKnowledge(
                name=f"knowledge-{minutes}",
                url="https://contoso.sharepoint.com/sites/KS",
                space_id=space_id,
                tenant_id=foreign_tenant.id if foreign else tenant_id,
                embedding_model_id=model.id,
                user_integration_id=(
                    foreign_connection.id if foreign else connection.id
                ),
                created_at=datetime(2026, 10, 1, tzinfo=timezone.utc)
                + timedelta(minutes=minutes),
            )
            session.add(item)
            await session.flush()
            return item.id

        organization_item = await knowledge(tenancy.organization, 1)
        own = await knowledge(tenancy.space, 2)
        distributed = await knowledge(tenancy.other_space, 3)
        await knowledge(tenancy.other_space, 4)
        foreign_distributed = await knowledge(tenancy.foreign_space, 5, foreign=True)
        # A row whose tenant disagrees with its space never shows.
        await knowledge(tenancy.space, 6, foreign=True)
        await session.execute(
            sa.insert(IntegrationKnowledgesSpaces),
            [
                dict(integration_knowledge_id=distributed, space_id=tenancy.space),
                dict(
                    integration_knowledge_id=foreign_distributed,
                    space_id=tenancy.space,
                ),
            ],
        )

    async with db_container(
        user=tenancy.caller(admin_user), tenant=tenancy.tenant
    ) as container:
        repo = container.space_repo()
        visible = await repo.get_visible_integration_knowledge_ids(
            tenancy.space, tenancy.organization
        )
        # The organization sees its own items only.
        organization_visible = await repo.get_visible_integration_knowledge_ids(
            tenancy.organization, None
        )
        loaded = [
            row.id
            for row in await repo._get_integration_knowledge_union(
                effective_space_ids_for(tenancy.space, tenancy.organization)
            )
            if row.tenant_id == tenant_id
        ]

    # Own, the organization parent's and distributed, in creation order.
    assert visible == [organization_item, own, distributed]
    assert organization_visible == [organization_item]
    # The aggregate loader's set, within the caller's tenant.
    assert loaded == visible


async def test_another_tenants_group_attached_to_a_space_grants_nothing(
    db_container, admin_user, tenancy, tenant_factory
):
    async with db_container() as container:
        session = container.session()
        foreign_tenant = await tenant_factory(session)
        foreign_group = await _group(session, tenant_id=foreign_tenant.id)
        await session.execute(
            sa.insert(SpacesUserGroups).values(
                space_id=tenancy.other_space, user_group_id=foreign_group, role="admin"
            )
        )

    # The caller's own record claims the group, as a corrupt sync could.
    caller = tenancy.caller(admin_user, foreign_group)
    async with db_container(user=caller, tenant=tenancy.tenant) as container:
        repo = container.space_repo()
        facts = await repo.get_space_access_facts(tenancy.other_space)
        many = await repo.get_spaces_access_facts([tenancy.other_space])

    assert not facts.group_members
    assert not many[tenancy.other_space].group_members
    assert not SpaceActor(caller, facts).can_read_space()


@dataclass
class ScopedResources:
    assistant: UUID
    default_assistant: UUID
    assistant_elsewhere: UUID
    app: UUID
    app_elsewhere: UUID


@pytest.fixture
async def scoped_resources(db_container, tenancy) -> ScopedResources:
    async with db_container() as container:
        session = container.session()

        async def assistant(space_id: UUID, *, is_default: bool = False) -> UUID:
            row = Assistants(
                name=f"assistant-{uuid4()}",
                user_id=tenancy.caller_id,
                space_id=space_id,
                logging_enabled=False,
                is_default=is_default,
                published=False,
            )
            session.add(row)
            await session.flush()
            return row.id

        async def app(space_id: UUID) -> UUID:
            row = Apps(
                name=f"app-{uuid4()}",
                tenant_id=tenancy.tenant_id,
                user_id=tenancy.caller_id,
                space_id=space_id,
                published=False,
            )
            session.add(row)
            await session.flush()
            return row.id

        return ScopedResources(
            assistant=await assistant(tenancy.space),
            default_assistant=await assistant(tenancy.space, is_default=True),
            assistant_elsewhere=await assistant(tenancy.other_space),
            app=await app(tenancy.space),
            app_elsewhere=await app(tenancy.other_space),
        )


def _key(
    tenant_id: UUID,
    *,
    owner: UUID | None,
    scope_type: ApiKeyScopeType,
    scope_id: UUID | None,
) -> ApiKeyV2InDB:
    return ApiKeyV2InDB(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_user_id=owner,
        ownership=ApiKeyOwnership.SERVICE if owner is None else ApiKeyOwnership.USER,
        name="key",
        key_prefix="sk_",
        key_suffix="test",
        key_type=ApiKeyType.SK,
        key_hash="hash",
        hash_version="sha256",
        permission=ApiKeyPermission.READ,
        state=ApiKeyState.ACTIVE,
        scope_type=scope_type,
        scope_id=scope_id,
    )


@pytest.mark.parametrize("ownership", ["user", "service"])
@pytest.mark.parametrize(
    ("scope_type", "scoped_to", "expected"),
    [
        # (scope, the resource the key names, the ids each space's facts hold)
        (
            ApiKeyScopeType.TENANT,
            None,
            {"space": (set(), set()), "other": (set(), set())},
        ),
        (
            ApiKeyScopeType.SPACE,
            "space",
            {"space": (set(), set()), "other": (set(), set())},
        ),
        (
            ApiKeyScopeType.ASSISTANT,
            "assistant",
            {"space": ({"assistant"}, set()), "other": (set(), set())},
        ),
        # A key for the default assistant (the personal chat's) reaches no space.
        (
            ApiKeyScopeType.ASSISTANT,
            "default_assistant",
            {"space": (set(), set()), "other": (set(), set())},
        ),
        (
            ApiKeyScopeType.ASSISTANT,
            "assistant_elsewhere",
            {"space": (set(), set()), "other": ({"assistant_elsewhere"}, set())},
        ),
        (
            ApiKeyScopeType.APP,
            "app",
            {"space": (set(), {"app"}), "other": (set(), set())},
        ),
        (
            ApiKeyScopeType.APP,
            "app_elsewhere",
            {"space": (set(), set()), "other": (set(), {"app_elsewhere"})},
        ),
    ],
)
async def test_a_key_brings_only_the_resource_it_is_scoped_to(
    db_container,
    admin_user,
    tenancy,
    scoped_resources,
    ownership,
    scope_type,
    scoped_to,
    expected,
):
    names = {
        "space": tenancy.space,
        **{
            name: getattr(scoped_resources, name)
            for name in ScopedResources.__dataclass_fields__
        },
    }
    key = _key(
        tenancy.tenant_id,
        owner=tenancy.caller_id if ownership == "user" else None,
        scope_type=scope_type,
        scope_id=names[scoped_to] if scoped_to else None,
    )
    if ownership == "user":
        caller = tenancy.caller(admin_user, tenancy.group).model_copy(
            update={"active_api_key": key}
        )
    else:
        async with db_container() as container:
            caller = await container.user_service()._build_service_user(key)

    async with db_container(user=caller, tenant=tenancy.tenant) as container:
        facts = await container.space_repo().get_spaces_access_facts(
            [tenancy.space, tenancy.other_space]
        )

    by_id = {value: name for name, value in names.items()}
    for space, space_id in (("space", tenancy.space), ("other", tenancy.other_space)):
        assistants, apps = expected[space]
        assert {by_id[id] for id in facts[space_id].assistant_ids} == assistants
        assert {by_id[id] for id in facts[space_id].app_ids} == apps
        assert facts[space_id].default_assistant_id is None
    # Memberships are the caller's own, whatever the key: none for a service key.
    if ownership == "service":
        assert not facts[tenancy.space].members
        assert not facts[tenancy.space].group_members
    else:
        assert {id: fact.role for id, fact in facts[tenancy.space].members.items()} == {
            tenancy.caller_id: "viewer"
        }
