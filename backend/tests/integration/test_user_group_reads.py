"""User-group reads load the members and nothing about them they do not return.

``GET /user-groups/`` serves the member pickers and returns each member as
``UserSparse`` (id, email, username, times). Loading the members' roles,
tenant and modules cost a batch of statements per 500 members.
"""

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from pydantic import BaseModel, EmailStr, ValidationError

from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import Users, usergroups_users_table
from eneo.main.models import ModelId
from eneo.user_groups.user_group import (
    UserGroupCreate,
    UserGroupState,
    UserGroupUpdate,
)
from eneo.user_groups.user_groups_repo import _listed_email
from eneo.users.user import UserAdd, UserState
from tests.integration.flows.statement_capture_support import capture_queries

pytestmark = pytest.mark.integration


@pytest.fixture
async def group(db_container, admin_user):
    async with db_container() as container:
        member = await container.user_repo().add(
            UserAdd(
                email=f"Group.Member.{uuid4().hex[:8]}@Example.com",
                username=f"group_member_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id) for role in admin_user.roles],
            )
        )
        repo = container.user_groups_repo()
        created = await repo.create_user_group(
            UserGroupCreate(
                name=f"group-{uuid4().hex[:8]}", tenant_id=admin_user.tenant_id
            )
        )
        updated = await repo.update_user_group(
            UserGroupUpdate(
                id=created.id, users=[ModelId(id=admin_user.id), ModelId(id=member.id)]
            )
        )
    assert updated is not None
    return updated, [admin_user, member]


@pytest.fixture
async def token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


async def test_the_reads_load_the_group_and_its_members_only(
    db_container, admin_user, group
) -> None:
    created, _ = group
    async with db_container() as container:
        repo = container.user_groups_repo()
        with capture_queries(container.session().sync_session.bind) as listed:
            groups = await repo.get_all_user_groups(tenant_id=admin_user.tenant_id)
        with capture_queries(container.session().sync_session.bind) as one:
            single = await repo.get_user_group(created.id)

    assert (len(listed), len(one)) == (2, 2), [q.sql for q in listed + one]
    assert single is not None
    assert {u.id for u in single.users} == {u.id for u in created.users}
    assert created.id in {g.id for g in groups}


async def test_the_responses_return_each_member_as_a_sparse_user(
    client, admin_user, group, token
) -> None:
    created, members = group
    headers = {"Authorization": f"Bearer {token}"}

    listed = await client.get("/api/v1/user-groups/", headers=headers)
    single = await client.get(f"/api/v1/user-groups/{created.id}/", headers=headers)

    assert (listed.status_code, single.status_code) == (200, 200)
    [from_list] = [g for g in listed.json()["items"] if g["id"] == str(created.id)]
    for body in (from_list, single.json()):
        assert body.keys() == {"id", "name", "created_at", "updated_at", "users"}
        assert body["name"] == created.name
        assert {
            u["id"]: (set(u), u["email"], u["username"]) for u in body["users"]
        } == {
            str(m.id): (
                {"id", "email", "username", "created_at", "updated_at"},
                m.email.lower(),
                m.username,
            )
            for m in members
        }


async def test_the_list_returns_a_member_with_an_empty_username(
    client, db_container, admin_user, token
) -> None:
    """The list validates into the public model only, which takes an empty username."""
    email = f"no.name.{uuid4().hex[:8]}@example.com"
    async with db_container() as container:
        member_id = await container.session().scalar(
            sa.insert(Users)
            .values(
                email=email, username="", state="active", tenant_id=admin_user.tenant_id
            )
            .returning(Users.id)
        )
        repo = container.user_groups_repo()
        created = await repo.create_user_group(
            UserGroupCreate(
                name=f"group-{uuid4().hex[:8]}", tenant_id=admin_user.tenant_id
            )
        )
        await container.session().execute(
            sa.insert(usergroups_users_table).values(
                user_group_id=created.id, user_id=member_id
            )
        )

    response = await client.get(
        "/api/v1/user-groups/", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200, response.text
    [listed] = [g for g in response.json()["items"] if g["id"] == str(created.id)]
    assert [(u["email"], u["username"]) for u in listed["users"]] == [(email, "")]


async def test_the_list_returns_a_member_whose_stored_email_is_malformed(
    client, db_container, admin_user, token
) -> None:
    """One unusable stored address does not fail every member picker."""
    email = f"not an address {uuid4().hex[:8]}"
    async with db_container() as container:
        member_id = await container.session().scalar(
            sa.insert(Users)
            .values(
                email=email,
                username="x",
                state="active",
                tenant_id=admin_user.tenant_id,
            )
            .returning(Users.id)
        )
        created = await container.user_groups_repo().create_user_group(
            UserGroupCreate(
                name=f"group-{uuid4().hex[:8]}", tenant_id=admin_user.tenant_id
            )
        )
        await container.session().execute(
            sa.insert(usergroups_users_table).values(
                user_group_id=created.id, user_id=member_id
            )
        )

    response = await client.get(
        "/api/v1/user-groups/", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200, response.text
    [listed] = [g for g in response.json()["items"] if g["id"] == str(created.id)]
    assert [u["email"] for u in listed["users"]] == [email]


async def _group_with(container, tenant_id, member_ids) -> UUID:
    created = await container.user_groups_repo().create_user_group(
        UserGroupCreate(name=f"group-{uuid4().hex[:8]}", tenant_id=tenant_id)
    )
    for member_id in member_ids:
        await container.session().execute(
            sa.insert(usergroups_users_table).values(
                user_group_id=created.id, user_id=member_id
            )
        )
    return created.id


async def test_the_list_keeps_each_tenants_groups_and_each_member_once(
    client, db_container, admin_user, token, tenant_factory, user_factory
) -> None:
    async with db_container() as container:
        session = container.session()
        other_tenant = await tenant_factory(session)
        other_member = await user_factory(session, tenant_id=other_tenant.id)
        first_member = await user_factory(session)
        second_member = await user_factory(session)
        other_member_id = other_member.id
        first_id, second_id = first_member.id, second_member.id
        foreign = await _group_with(container, other_tenant.id, [other_member_id])
        shared = await _group_with(
            container, admin_user.tenant_id, [first_id, second_id]
        )
        overlapping = await _group_with(container, admin_user.tenant_id, [first_id])
        deleted = await _group_with(container, admin_user.tenant_id, [first_id])
        await container.session().execute(
            sa.update(UserGroups)
            .where(UserGroups.id == deleted)
            .values(state=UserGroupState.DELETED)
        )

    response = await client.get(
        "/api/v1/user-groups/", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200, response.text
    members = {
        group["id"]: sorted(user["id"] for user in group["users"])
        for group in response.json()["items"]
    }
    assert str(foreign) not in members
    assert str(deleted) not in members
    assert members[str(shared)] == sorted([str(first_id), str(second_id)])
    assert members[str(overlapping)] == [str(first_id)]
    assert str(other_member_id) not in {id for ids in members.values() for id in ids}


@pytest.mark.parametrize(
    "stored",
    [
        "anna@example.com",
        "Anna.Berg+tag@Example.COM",
        "anna@xn--rebro-jua.se",
        "ANNA@XN--REBRO-JUA.SE",
        "  anna@example.com  ",
        "Anna Berg <anna@example.com>",
        "anna..berg@example.com",
        "anna@example.test",
        "åsa@example.com",
        "xn--anna@example.com",
        "anna@example.com.",
        f"{'a' * 65}@example.com",
        f"anna@{'a.' * 130}se",
        "not an address",
    ],
)
def test_a_listed_email_is_what_validation_gives_or_the_stored_value(stored) -> None:
    """The list agrees with ``GET /user-groups/{id}/`` on every address it could
    return before, and shows the rest as stored."""

    class Member(BaseModel):
        email: EmailStr

    try:
        validated = Member(email=stored).email
    except ValidationError:
        validated = stored

    assert _listed_email(stored).lower() == validated.lower()
