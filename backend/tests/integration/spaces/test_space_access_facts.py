"""The narrow space reads behind polled and admin views: the caller's access
facts and the ids of the integration knowledge a space shows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.integration_knowledge_spaces_table import (
    IntegrationKnowledgesSpaces,
)
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.spaces_table import Spaces, SpacesUserGroups, SpacesUsers
from eneo.database.tables.user_groups_table import UserGroups
from eneo.main.exceptions import NotFoundException
from eneo.spaces.utils.space_utils import effective_space_ids_for
from eneo.user_groups.user_group import UserGroupState
from eneo.users.user import UserGroupInDBRead, UserInDB


@dataclass
class Tenancy:
    """A fresh tenant, so its organization space holds only this test's rows."""

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
    return Tenancy(
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
    async with db_container(user=caller) as container:
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
    async with db_container(user=tenancy.caller(admin_user)) as container:
        repo = container.space_repo()
        with pytest.raises(NotFoundException):
            await repo.get_space_access_facts(tenancy.foreign_space)
        with pytest.raises(NotFoundException):
            await repo.get_space_access_facts(uuid4())


async def test_facts_for_many_spaces_leave_out_other_tenants(
    db_container, admin_user, tenancy
):
    caller = tenancy.caller(admin_user, tenancy.group)
    async with db_container(user=caller) as container:
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

    async with db_container(user=tenancy.caller(admin_user)) as container:
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
