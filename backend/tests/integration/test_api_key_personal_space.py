"""A personal space's owner can hold keys for it, and the keys work.

A personal space has no member rows and cannot be edited, so neither the
space-admin rule for creating a space-scoped key nor the member-row rule for
using a scoped key can ever be met there. Its owner stands in for both.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.database.tables.spaces_table import Spaces
from eneo.users.user import UserAdd, UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def owner(db_container):
    async with db_container() as container:
        return await container.user_repo().get_user_by_email("test@example.com")


@pytest.fixture
async def owner_headers(db_container, patch_auth_service_jwt, owner):
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(owner)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def personal_space_id(client, owner_headers) -> str:
    response = await client.get("/api/v1/spaces/type/personal/", headers=owner_headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


@pytest.fixture
async def someone_elses_personal_space_id(db_container, owner) -> str:
    async with db_container() as container:
        other = await container.user_repo().add(
            UserAdd(
                email=f"other-{uuid4().hex[:8]}@example.com",
                username=f"other_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=owner.tenant_id,
            )
        )
        space = Spaces(
            name="Someone else's personal space",
            tenant_id=owner.tenant_id,
            user_id=other.id,
        )
        session = container.session()
        session.add(space)
        await session.flush()
        return str(space.id)


async def _create_key(client, headers, **overrides):
    body = {
        "name": "Personal space key",
        "key_type": "sk_",
        "permission": "read",
        "scope_type": "space",
        **overrides,
    }
    return await client.post("/api/v1/api-keys", json=body, headers=headers)


async def test_owner_creates_and_uses_a_key_for_their_personal_space(
    client, owner_headers, personal_space_id
):
    created = await _create_key(client, owner_headers, scope_id=personal_space_id)
    assert created.status_code == 201, created.text

    read = await client.get(
        f"/api/v1/spaces/{personal_space_id}/",
        headers={"X-API-Key": created.json()["secret"]},
    )
    assert read.status_code == 200, read.text
    assert read.json()["id"] == personal_space_id


async def test_a_key_for_an_assistant_in_the_personal_space_authenticates(
    client, owner_headers, personal_space_id
):
    assistant = await client.post(
        f"/api/v1/spaces/{personal_space_id}/applications/assistants/",
        json={"name": "Personal assistant"},
        headers=owner_headers,
    )
    assert assistant.status_code == 201, assistant.text
    assistant_id = assistant.json()["id"]

    created = await _create_key(
        client, owner_headers, scope_type="assistant", scope_id=assistant_id
    )
    assert created.status_code == 201, created.text

    read = await client.get(
        f"/api/v1/assistants/{assistant_id}/",
        headers={"X-API-Key": created.json()["secret"]},
    )
    assert read.status_code == 200, read.text


async def test_a_tenant_admin_cannot_create_a_key_for_another_users_personal_space(
    client, owner_headers, someone_elses_personal_space_id
):
    response = await _create_key(
        client, owner_headers, scope_id=someone_elses_personal_space_id
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "insufficient_permission"


async def test_a_service_key_cannot_be_scoped_to_a_personal_space(
    client, owner_headers, personal_space_id
):
    response = await _create_key(
        client, owner_headers, scope_id=personal_space_id, ownership="service"
    )
    assert response.status_code == 400, response.text
    assert "personal space" in response.json()["message"]
