"""The documents and skipped-file routes of an integration item decide access
from the caller's access facts and the ids a space shows, not from the space
aggregate; for every kind of caller the outcome is the one the aggregate gave.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.actors.actors.space_actor import SpaceAccessFacts
from eneo.authentication.auth_models import (
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
)
from eneo.database.tables.app_table import Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.integration_knowledge_spaces_table import (
    IntegrationKnowledgesSpaces,
)
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.spaces_table import Spaces, SpacesUserGroups, SpacesUsers
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import usergroups_users_table
from eneo.main.exceptions import NotFoundException, UnauthorizedException
from eneo.spaces.space import Space
from eneo.user_groups.user_group import UserGroupState
from eneo.users.user import UserInDB


@dataclass
class Tenant:
    """A fresh tenant: an organization, two shared child spaces and a
    personal space, with members of every kind and items of every reach."""

    id: UUID
    spaces: dict[str, UUID]
    users: dict[str, UUID]
    resources: dict[str, UUID]
    items: dict[str, UUID] = field(default_factory=dict)


async def _space(session, tenant_id, name, *, parent=None, owner=None) -> UUID:
    space = Spaces(
        name=name, tenant_id=tenant_id, user_id=owner, tenant_space_id=parent
    )
    session.add(space)
    await session.flush()
    return space.id


@pytest.fixture
async def tenant(
    db_container,
    tenant_factory,
    user_factory,
    user_integration_factory,
    embedding_model_factory,
) -> Tenant:
    async with db_container() as container:
        session = container.session()
        tenant_id = (await tenant_factory(session)).id
        users = {
            name: (await user_factory(session, tenant_id=tenant_id)).id
            for name in (
                "viewer",
                "editor",
                "admin",
                "group_member",
                "deleted_group_member",
                "org_admin",
                "org_viewer",
                "personal_owner",
                "outsider",
            )
        }
        organization = await _space(session, tenant_id, "Org")
        spaces = {
            "organization": organization,
            "shared": await _space(session, tenant_id, "Barn", parent=organization),
            "sibling": await _space(session, tenant_id, "Ekonomi", parent=organization),
            "personal": await _space(
                session,
                tenant_id,
                "Personal",
                parent=organization,
                owner=users["personal_owner"],
            ),
        }
        await session.execute(
            sa.insert(SpacesUsers),
            [
                dict(space_id=spaces["shared"], user_id=users[role], role=role)
                for role in ("viewer", "editor", "admin")
            ]
            + [
                dict(space_id=organization, user_id=users["org_admin"], role="admin"),
                dict(space_id=organization, user_id=users["org_viewer"], role="viewer"),
            ],
        )
        groups = {}
        for name, state in (("group", None), ("deleted_group", UserGroupState.DELETED)):
            group = UserGroups(
                name=f"{name}-{uuid4()}",
                tenant_id=tenant_id,
                state=None if state is None else state.value,
            )
            session.add(group)
            await session.flush()
            groups[name] = group.id
        await session.execute(
            sa.insert(SpacesUserGroups),
            [
                dict(
                    space_id=spaces["shared"],
                    user_group_id=groups["group"],
                    role="editor",
                ),
                dict(
                    space_id=spaces["shared"],
                    user_group_id=groups["deleted_group"],
                    role="admin",
                ),
            ],
        )
        await session.execute(
            sa.insert(usergroups_users_table),
            [
                dict(user_id=users["group_member"], user_group_id=groups["group"]),
                dict(
                    user_id=users["deleted_group_member"],
                    user_group_id=groups["deleted_group"],
                ),
            ],
        )

        resources = {}
        for name, space, is_default in (
            ("assistant", "shared", False),
            ("default_assistant", "shared", True),
            ("sibling_assistant", "sibling", False),
        ):
            assistant = Assistants(
                name=name,
                user_id=users["admin"],
                space_id=spaces[space],
                logging_enabled=False,
                is_default=is_default,
                published=False,
            )
            session.add(assistant)
            await session.flush()
            resources[name] = assistant.id
        for name, space in (("app", "shared"), ("sibling_app", "sibling")):
            app = Apps(
                name=name,
                tenant_id=tenant_id,
                user_id=users["admin"],
                space_id=spaces[space],
                published=False,
            )
            session.add(app)
            await session.flush()
            resources[name] = app.id

        model = await embedding_model_factory(session)
        connection = await user_integration_factory(session, tenant_id=tenant_id)
        built = Tenant(id=tenant_id, spaces=spaces, users=users, resources=resources)
        for name, space in (
            ("organization_item", "organization"),
            ("shared_item", "shared"),
            ("sibling_item", "sibling"),
            ("distributed_item", "sibling"),
            ("personal_item", "personal"),
        ):
            item = IntegrationKnowledge(
                name=name,
                url=f"https://contoso.sharepoint.com/sites/{name}",
                folder_path=f"/{name}",
                resource_type="site",
                space_id=spaces[space],
                tenant_id=tenant_id,
                embedding_model_id=model.id,
                user_integration_id=connection.id,
            )
            session.add(item)
            await session.flush()
            built.items[name] = item.id
        await session.execute(
            sa.insert(IntegrationKnowledgesSpaces).values(
                integration_knowledge_id=built.items["distributed_item"],
                space_id=spaces["shared"],
            )
        )
    return built


def _key(
    tenant: Tenant,
    *,
    owner: str | None,
    scope: ApiKeyScopeType,
    scoped_to: UUID | None = None,
    permission: ApiKeyPermission = ApiKeyPermission.READ,
) -> ApiKeyV2InDB:
    return ApiKeyV2InDB(
        id=uuid4(),
        tenant_id=tenant.id,
        owner_user_id=None if owner is None else tenant.users[owner],
        ownership=ApiKeyOwnership.SERVICE if owner is None else ApiKeyOwnership.USER,
        name="key",
        key_prefix="sk_",
        key_suffix="test",
        key_type=ApiKeyType.SK,
        key_hash="hash",
        hash_version="sha256",
        permission=permission,
        state=ApiKeyState.ACTIVE,
        scope_type=scope,
        scope_id=scoped_to,
    )


async def _callers(db_container, tenant: Tenant, foreign_user_id: UUID) -> dict:
    """Every kind of caller: members by role and group, personal owners,
    outsiders, user-owned and service keys of every scope."""
    async with db_container() as container:
        repo = container.user_repo()
        users: dict[str, UserInDB] = {}
        for name, user_id in tenant.users.items():
            user = await repo.get_user_by_id(user_id)
            assert user is not None
            users[name] = user
        foreign = await repo.get_user_by_id(foreign_user_id)
        assert foreign is not None
        callers: dict[str, UserInDB] = {**users, "foreign_user": foreign}

        spaces, resources = tenant.spaces, tenant.resources
        key_cases = {
            "tenant_key": dict(scope=ApiKeyScopeType.TENANT),
            "shared_space_key": dict(
                scope=ApiKeyScopeType.SPACE, scoped_to=spaces["shared"]
            ),
            "sibling_space_key": dict(
                scope=ApiKeyScopeType.SPACE, scoped_to=spaces["sibling"]
            ),
            "assistant_key": dict(
                scope=ApiKeyScopeType.ASSISTANT, scoped_to=resources["assistant"]
            ),
            "default_assistant_key": dict(
                scope=ApiKeyScopeType.ASSISTANT,
                scoped_to=resources["default_assistant"],
            ),
            "sibling_assistant_key": dict(
                scope=ApiKeyScopeType.ASSISTANT,
                scoped_to=resources["sibling_assistant"],
            ),
            "app_key": dict(scope=ApiKeyScopeType.APP, scoped_to=resources["app"]),
            "sibling_app_key": dict(
                scope=ApiKeyScopeType.APP, scoped_to=resources["sibling_app"]
            ),
        }
        for name, case in key_cases.items():
            for member in ("viewer", "outsider", "org_admin"):
                callers[f"{member}_{name}"] = users[member].model_copy(
                    update={"active_api_key": _key(tenant, owner=member, **case)}
                )
            for permission in ApiKeyPermission:
                key = _key(tenant, owner=None, permission=permission, **case)
                callers[
                    f"service_{permission.value}_{name}"
                ] = await container.user_service()._build_service_user(key)
    return callers


def _aggregate_outcome(container, space: Space | None, item_id: UUID):
    """What the routes decided from the space aggregate before."""
    if space is None:
        return 404, None
    actor = container.actor_manager().get_space_actor_from_space(space)
    if not (actor.can_read_space() and actor.can_read_integrations()):
        return 403, None
    try:
        item = space.get_integration_knowledge(integration_knowledge_id=item_id)
    except NotFoundException:
        return 404, None
    return 200, (
        item.id,
        item.integration_type,
        item.url,
        item.folder_path,
        item.resource_type,
    )


async def _narrow_outcome(container, space_id: UUID, item_id: UUID):
    service = container.integration_knowledge_service()
    try:
        await service.require_readable_knowledge(space_id, item_id)
        location = await service.get_readable_knowledge(space_id, item_id)
    except NotFoundException:
        return 404, None
    except UnauthorizedException:
        return 403, None
    return 200, (
        location.id,
        location.integration_type,
        location.url,
        location.folder_path,
        location.resource_type,
    )


async def test_every_caller_gets_what_the_space_aggregate_gave(
    db_container, tenant, tenant_factory, user_factory
):
    async with db_container() as container:
        session = container.session()
        foreign_tenant_id = (await tenant_factory(session)).id
        foreign_user_id = (await user_factory(session, tenant_id=foreign_tenant_id)).id
        foreign_space = await _space(session, foreign_tenant_id, "Annan")
        await session.execute(
            sa.insert(SpacesUsers).values(
                space_id=foreign_space, user_id=foreign_user_id, role="admin"
            )
        )
    callers = await _callers(db_container, tenant, foreign_user_id)
    space_ids = {**tenant.spaces, "foreign": foreign_space, "unknown": uuid4()}
    item_ids = {**tenant.items, "unknown": uuid4()}

    outcomes: dict[str, set[int]] = {}
    for caller_name, caller in callers.items():
        async with db_container(user=caller) as container:
            for space_name, space_id in space_ids.items():
                facts = space = None
                try:
                    facts = await container.space_repo().get_space_access_facts(
                        space_id
                    )
                    space = await container.space_repo().one(id=space_id)
                except NotFoundException:
                    assert facts is None, (caller_name, space_name)
                else:
                    # The facts answer this caller's checks as the aggregate does.
                    narrow = container.actor_manager().get_space_actor(facts)
                    full = container.actor_manager().get_space_actor(
                        SpaceAccessFacts.from_space(space)
                    )
                    for check in (
                        "can_read_space",
                        "can_read_integrations",
                        "can_edit_integrations",
                        "can_delete_integrations",
                    ):
                        assert getattr(narrow, check)() == getattr(full, check)(), (
                            caller_name,
                            space_name,
                            check,
                        )
                for item_name, item_id in item_ids.items():
                    expected = _aggregate_outcome(container, space, item_id)
                    actual = await _narrow_outcome(container, space_id, item_id)
                    assert actual == expected, (caller_name, space_name, item_name)
                    outcomes.setdefault(caller_name, set()).add(expected[0])

    # Every outcome occurs, so the comparison covers each branch.
    assert {status for seen in outcomes.values() for status in seen} == {
        200,
        403,
        404,
    }
    assert 200 in outcomes["viewer"] and 200 in outcomes["group_member"]
    assert outcomes["deleted_group_member"] <= {403, 404}
    assert 200 in outcomes["service_read_tenant_key"]
    assert 200 in outcomes["viewer_assistant_key"]
    assert outcomes["viewer_default_assistant_key"] <= {403, 404}
    assert outcomes["foreign_user"] <= {403, 404}
