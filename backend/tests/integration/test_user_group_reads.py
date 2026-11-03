"""User-group reads load the members and nothing about them they do not return.

``GET /user-groups/`` serves the member pickers and returns each member as
``UserSparse`` (id, email, username, times). Loading the members' roles,
tenant and modules cost a batch of statements per 500 members.
"""

from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.users_table import Users, usergroups_users_table
from eneo.main.models import ModelId
from eneo.user_groups.user_group import UserGroupCreate, UserGroupUpdate
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
