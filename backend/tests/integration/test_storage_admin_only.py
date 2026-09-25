"""Tenant storage usage is an admin view.

``GET /api/v1/storage/spaces/`` lists every shared space in the tenant with
its members' ids, emails and roles; ``GET /api/v1/storage/`` totals the
tenant's storage. Both feed the admin usage page, so a session user without
``Permission.ADMIN`` must be refused even when holding every other permission.

Run with:
    uv run pytest tests/integration/test_storage_admin_only.py -v
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

STORAGE_ROUTES = ["/api/v1/storage/", "/api/v1/storage/spaces/"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _user_token(db_container, permissions: list[Permission]) -> str:
    async with db_container() as container:
        admin = await container.user_repo().get_user_by_email("test@example.com")
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"storage-{uuid4().hex[:8]}",
                permissions=permissions,
                tenant_id=admin.tenant_id,
            )
        )
        user = await container.user_repo().add(
            UserAdd(
                email=f"storage-{uuid4().hex[:8]}@example.com",
                username=f"storage_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )
        return container.auth_service().create_access_token_for_user(user)


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.fixture
async def shared_space(client, admin_token):
    resp = await client.post(
        "/api/v1/spaces/",
        json={"name": f"storage-space-{uuid4().hex[:8]}"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.parametrize("path", STORAGE_ROUTES)
async def test_a_user_without_admin_cannot_read_tenant_storage(
    client, db_container, patch_auth_service_jwt, shared_space, path
):
    token = await _user_token(
        db_container, [p for p in Permission if p is not Permission.ADMIN]
    )

    resp = await client.get(path, headers=_auth(token))

    assert resp.status_code == 403, resp.text
    assert "test@example.com" not in resp.text


async def test_an_admin_reads_tenant_storage_and_every_shared_space(
    client, admin_user, admin_token, shared_space
):
    resp = await client.get("/api/v1/storage/", headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    assert set(resp.json()) == {"total_used", "personal_used", "shared_used", "limit"}

    resp = await client.get("/api/v1/storage/spaces/", headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    spaces = {item["id"]: item for item in resp.json()["items"]}
    assert shared_space["id"] in spaces
    members = spaces[shared_space["id"]]["members"]
    assert [m["email"] for m in members] == [admin_user.email]


@pytest.mark.parametrize("path", STORAGE_ROUTES)
async def test_an_admins_tenant_api_key_still_reads_tenant_storage(
    client, admin_user_api_key, shared_space, path
):
    resp = await client.get(path, headers={"X-API-Key": admin_user_api_key.key})

    assert resp.status_code == 200, resp.text
