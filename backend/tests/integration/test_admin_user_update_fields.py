"""PATCH /api/v1/users/admin/{id}/ changes only the fields it is given."""

from __future__ import annotations

import pytest


@pytest.fixture
async def admin_headers(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
        return {"Authorization": f"Bearer {token}"}


def _url(user) -> str:
    return f"/api/v1/users/admin/{user.id}/"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_role_alone_changes_the_role_and_leaves_the_state(
    client, admin_headers, admin_user
):
    role_id = str(admin_user.roles[0].id)

    response = await client.patch(
        _url(admin_user), headers=admin_headers, json={"role": {"id": role_id}}
    )

    assert response.status_code == 200, response.text
    assert response.json()["state"] == admin_user.state.value
    assert [r["id"] for r in response.json()["roles"]] == [role_id]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_state_alone_changes_the_state_and_leaves_the_roles(
    client, admin_headers, admin_user
):
    response = await client.patch(
        _url(admin_user), headers=admin_headers, json={"state": "active"}
    )

    assert response.status_code == 200, response.text
    assert [r["id"] for r in response.json()["roles"]] == [
        str(r.id) for r in admin_user.roles
    ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_an_empty_update_changes_nothing(client, admin_headers, admin_user):
    response = await client.patch(_url(admin_user), headers=admin_headers, json={})

    assert response.status_code == 200, response.text
    assert response.json()["state"] == admin_user.state.value
