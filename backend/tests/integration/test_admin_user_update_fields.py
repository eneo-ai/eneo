"""PATCH /api/v1/users/admin/{id}/ changes only the fields it is given."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.main.models import ModelId
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def admin_headers(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def make_role(db_container, admin_user):
    async def _make_role():
        async with db_container() as container:
            return await container.role_repo().create_role(
                RoleCreate(
                    name=f"role-{uuid4().hex[:8]}",
                    permissions=[],
                    tenant_id=admin_user.tenant_id,
                )
            )

    return _make_role


@pytest.fixture
async def first_role(make_role):
    return await make_role()


@pytest.fixture
async def target_user(db_container, admin_user, first_role):
    """An active user with one role, other than the administrator who calls."""
    async with db_container() as container:
        return await container.user_repo().add(
            UserAdd(
                email=f"target-{uuid4().hex[:8]}@example.com",
                username=f"target_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=first_role.id)],
            )
        )


def _url(user) -> str:
    return f"/api/v1/users/admin/{user.id}/"


async def _stored(db_container, user):
    async with db_container() as container:
        stored = await container.user_repo().get_user_by_id(user.id)
    return stored.state, [role.id for role in stored.roles]


async def test_a_role_alone_changes_the_role_and_leaves_the_state(
    client, admin_headers, db_container, target_user, make_role
):
    second_role = await make_role()

    response = await client.patch(
        _url(target_user),
        headers=admin_headers,
        json={"role": {"id": str(second_role.id)}},
    )

    assert response.status_code == 200, response.text
    assert await _stored(db_container, target_user) == (
        UserState.ACTIVE,
        [second_role.id],
    )


async def test_a_state_alone_changes_the_state_and_leaves_the_roles(
    client, admin_headers, db_container, target_user, first_role
):
    response = await client.patch(
        _url(target_user), headers=admin_headers, json={"state": "inactive"}
    )

    assert response.status_code == 200, response.text
    assert await _stored(db_container, target_user) == (
        UserState.INACTIVE,
        [first_role.id],
    )


async def test_a_null_role_is_the_same_as_no_role(
    client, admin_headers, db_container, target_user, first_role
):
    response = await client.patch(
        _url(target_user),
        headers=admin_headers,
        json={"role": None, "state": "inactive"},
    )

    assert response.status_code == 200, response.text
    assert await _stored(db_container, target_user) == (
        UserState.INACTIVE,
        [first_role.id],
    )


async def test_an_empty_update_changes_nothing(
    client, admin_headers, db_container, target_user, first_role
):
    response = await client.patch(_url(target_user), headers=admin_headers, json={})

    assert response.status_code == 200, response.text
    assert await _stored(db_container, target_user) == (
        UserState.ACTIVE,
        [first_role.id],
    )
