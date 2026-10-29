"""Assistant editors learn that a widget publishes the assistant, and nothing more."""

from uuid import uuid4

import pytest

from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _user_token(db_container, permissions: list[Permission]) -> tuple[str, str]:
    async with db_container() as container:
        admin = await container.user_repo().get_user_by_email("test@example.com")
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"assistant-editor-{uuid4().hex[:8]}",
                permissions=permissions,
                tenant_id=admin.tenant_id,
            )
        )
        user = await container.user_repo().add(
            UserAdd(
                email=f"assistant-editor-{uuid4().hex[:8]}@example.com",
                username=f"assistant_editor_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )
        token = container.auth_service().create_access_token_for_user(user)
        return str(user.id), token


async def _status(client, token, assistant_id):
    return await client.get(
        f"/api/v1/assistants/{assistant_id}/widget-status/", headers=_auth(token)
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_space_editor_without_widget_access_sees_the_widget_publishes_the_assistant(
    client, db_container, patch_auth_service_jwt, admin_token, active_widget
):
    space_id = active_widget["space_id"]
    assistant_id = active_widget["target_id"]
    editor_id, editor_token = await _user_token(db_container, [Permission.ASSISTANTS])
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/members/",
        json={"id": editor_id, "role": "editor"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = await client.get(
        f"/api/v1/spaces/{space_id}/widgets/", headers=_auth(editor_token)
    )
    assert resp.status_code == 403, resp.text

    resp = await _status(client, editor_token, assistant_id)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"serves_active_widget": True}

    resp = await client.post(
        f"/api/v1/widgets/{active_widget['id']}/pause/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text
    resp = await _status(client, editor_token, assistant_id)
    assert resp.json() == {"serves_active_widget": False}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_only_an_active_widget_of_this_assistant_counts(
    client, admin_token, active_widget
):
    resp = await client.post(
        f"/api/v1/spaces/{active_widget['space_id']}/applications/assistants/",
        json={"name": "Grannen"},
        headers=_auth(admin_token),
    )
    neighbour = resp.json()["id"]
    resp = await _status(client, admin_token, neighbour)
    assert resp.json() == {"serves_active_widget": False}

    resp = await client.post(
        f"/api/v1/spaces/{active_widget['space_id']}/widgets/",
        json={"target_id": neighbour, "name": "Utkast"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    resp = await _status(client, admin_token, neighbour)
    assert resp.json() == {"serves_active_widget": False}

    resp = await client.post(
        f"/api/v1/widgets/{active_widget['id']}/archive/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text
    resp = await _status(client, admin_token, active_widget["target_id"])
    assert resp.json() == {"serves_active_widget": False}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_someone_who_cannot_read_the_assistant_learns_nothing(
    client, db_container, patch_auth_service_jwt, active_widget
):
    _, outsider_token = await _user_token(db_container, [Permission.ASSISTANTS])
    resp = await _status(client, outsider_token, active_widget["target_id"])
    assert resp.status_code in (403, 404), resp.text
    assert "serves_active_widget" not in resp.text
