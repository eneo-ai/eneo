"""Shared authenticated widget fixtures."""

from uuid import uuid4

import pytest


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt):
    async with db_container() as container:
        user = await container.user_repo().get_user_by_email("test@example.com")
        return container.auth_service().create_access_token_for_user(user)


@pytest.fixture
async def active_widget(client, admin_token):
    resp = await client.post(
        "/api/v1/spaces/",
        json={"name": f"ask-widget-{uuid4().hex[:8]}"},
        headers=_auth(admin_token),
    )
    space_id = resp.json()["id"]
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/applications/assistants/",
        json={"name": "Kommunassistenten"},
        headers=_auth(admin_token),
    )
    assistant_id = resp.json()["id"]
    await client.post(
        f"/api/v1/assistants/{assistant_id}/publish/",
        params={"published": "true"},
        headers=_auth(admin_token),
    )
    resp = await client.post(
        f"/api/v1/spaces/{space_id}/widgets/",
        json={"target_id": assistant_id, "name": "Webbchatt"},
        headers=_auth(admin_token),
    )
    widget = resp.json()
    await client.patch(
        f"/api/v1/widgets/{widget['id']}/",
        json={
            "revision": (
                await client.get(
                    f"/api/v1/widgets/{widget['id']}/", headers=_auth(admin_token)
                )
            ).json()["revision"],
            "allowed_origins": ["https://www.kommun.se"],
        },
        headers=_auth(admin_token),
    )
    resp = await client.post(
        f"/api/v1/widgets/{widget['id']}/activate/", headers=_auth(admin_token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()
