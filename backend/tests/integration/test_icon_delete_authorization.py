"""An icon id never authorizes removing an icon another resource still shows.

Icon ids are public: ``GET /icons/{id}/`` is unauthenticated and the id sits in
every ``<img src>``. Assistants, apps, spaces and group chats reference icons
with ``ON DELETE SET NULL``, so a delete that only checks the tenant silently
clears whatever resource uses the icon.
"""

from uuid import uuid4

import pytest

from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


async def _headers(db_container, user) -> dict[str, str]:
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def owner(db_container, admin_user, patch_auth_service_jwt) -> dict[str, str]:
    return await _headers(db_container, admin_user)


@pytest.fixture
async def member(db_container, admin_user, patch_auth_service_jwt) -> dict[str, str]:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"member-{uuid4().hex[:8]}",
                permissions=[Permission.ASSISTANTS, Permission.SHARED_SPACES],
                tenant_id=admin_user.tenant_id,
            )
        )
        user = await container.user_repo().add(
            UserAdd(
                email=f"member-{uuid4().hex[:8]}@example.com",
                username=f"member_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )
    return await _headers(db_container, user)


async def _assistant_with_icon(
    client, headers: dict[str, str], icon_id: str | None = None
) -> tuple[str, str]:
    """Create an assistant in a new space of the caller and show an icon on it."""
    if icon_id is None:
        uploaded = await client.post(
            "/api/v1/icons/",
            files={"file": ("icon.png", _PNG, "image/png")},
            headers=headers,
        )
        assert uploaded.status_code == 200, uploaded.text
        icon_id = uploaded.json()["id"]
    space = await client.post(
        "/api/v1/spaces/", json={"name": f"Icons {uuid4().hex[:8]}"}, headers=headers
    )
    assert space.status_code == 201, space.text
    assistant = await client.post(
        f"/api/v1/spaces/{space.json()['id']}/applications/assistants/",
        json={"name": "Has an icon"},
        headers=headers,
    )
    assert assistant.status_code == 201, assistant.text
    assistant_id = assistant.json()["id"]
    attached = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"icon_id": icon_id},
        headers=headers,
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["icon_id"] == icon_id
    return assistant_id, icon_id


async def _shown_icon(client, headers: dict[str, str], assistant_id: str) -> str | None:
    response = await client.get(f"/api/v1/assistants/{assistant_id}/", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["icon_id"]


@pytest.mark.parametrize("caller", ["member", "owner"])
async def test_an_icon_an_assistant_shows_cannot_be_deleted(
    client, owner, member, caller
):
    assistant_id, icon_id = await _assistant_with_icon(client, owner)

    response = await client.delete(
        f"/api/v1/icons/{icon_id}/",
        headers={"member": member, "owner": owner}[caller],
    )

    assert response.status_code == 403, response.text
    assert await _shown_icon(client, owner, assistant_id) == icon_id
    assert (await client.get(f"/api/v1/icons/{icon_id}/")).status_code == 200


async def test_the_owner_removes_an_icon_by_clearing_it_first(client, owner):
    assistant_id, icon_id = await _assistant_with_icon(client, owner)

    cleared = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"icon_id": None},
        headers=owner,
    )
    assert cleared.status_code == 200, cleared.text
    deleted = await client.delete(f"/api/v1/icons/{icon_id}/", headers=owner)

    assert deleted.status_code == 204, deleted.text
    assert (await client.get(f"/api/v1/icons/{icon_id}/")).status_code == 404


async def test_deleting_a_resource_keeps_an_icon_another_resource_shows(
    client, owner, member
):
    owned_assistant, icon_id = await _assistant_with_icon(client, owner)
    borrowing_assistant, _ = await _assistant_with_icon(client, member, icon_id)

    deleted = await client.delete(
        f"/api/v1/assistants/{borrowing_assistant}/", headers=member
    )

    assert deleted.status_code == 204, deleted.text
    assert await _shown_icon(client, owner, owned_assistant) == icon_id
    assert (await client.get(f"/api/v1/icons/{icon_id}/")).status_code == 200


async def test_deleting_the_last_resource_that_shows_an_icon_deletes_it(client, owner):
    assistant_id, icon_id = await _assistant_with_icon(client, owner)

    deleted = await client.delete(f"/api/v1/assistants/{assistant_id}/", headers=owner)

    assert deleted.status_code == 204, deleted.text
    assert (await client.get(f"/api/v1/icons/{icon_id}/")).status_code == 404
