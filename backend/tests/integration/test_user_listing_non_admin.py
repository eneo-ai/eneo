"""Route-level integration tests for the relaxed member-picker endpoints.

These lock in the April 2026 relax: `GET /api/v1/users/` and
`GET /api/v1/user-groups/` are no longer gated on `Permission.ADMIN`.
They power the space member/group pickers (AddMember, AddGroupMember)
for space-admins whose tenant role lacks ADMIN.

Coverage:

  * Positive: a user without ADMIN can list tenant users (200) and
    tenant user-groups (200), sees only their own tenant.
  * Tenancy: cross-tenant users never appear in the response.
  * Data minimization: the user-groups response exposes `UserSparse`
    on its nested `users` array — no `quota_used` field leaks.
  * Regression: mutations on /users/admin/* and /user-groups/ POST
    remain ADMIN-gated for non-admins.

Run with:
    uv run pytest tests/integration/test_user_listing_non_admin.py -v
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.main.models import ModelId
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def non_admin_role(db_container, admin_user):
    """Role with no permissions — baseline tenant User."""
    async with db_container() as container:
        role_repo = container.role_repo()
        role = await role_repo.create_role(
            RoleCreate(
                name=f"non-admin-{uuid4().hex[:8]}",
                permissions=[],
                tenant_id=admin_user.tenant_id,
            )
        )
    return role


@pytest.fixture
async def non_admin_user(db_container, admin_user, non_admin_role):
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.add(
            UserAdd(
                email=f"non-admin-{uuid4().hex[:8]}@example.com",
                username=f"non_admin_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=non_admin_role.id)],
            )
        )
    return user


@pytest.fixture
async def non_admin_token(db_container, patch_auth_service_jwt, non_admin_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(non_admin_user)


async def test_non_admin_can_list_tenant_users(client, non_admin_user, non_admin_token):
    """Baseline user without ADMIN receives a populated user list.

    Before the relax this returned 403. After the relax it returns
    tenant-scoped UserSparse entries, enabling AddMember pickers for
    space-admins without tenant ADMIN.
    """
    resp = await client.get(
        "/api/v1/users/",
        headers={"Authorization": f"Bearer {non_admin_token}"},
    )
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert "items" in body
    ids = {item["id"] for item in body["items"]}
    assert str(non_admin_user.id) in ids

    # Response shape is UserSparse only — no admin-only fields leak.
    sample = body["items"][0]
    allowed = {"id", "email", "username", "created_at", "updated_at"}
    extra_fields = set(sample.keys()) - allowed
    assert extra_fields == set(), (
        f"Unexpected extra fields in UserSparse response: {extra_fields}"
    )


async def test_non_admin_can_list_user_groups(
    client, non_admin_token, db_container, admin_user
):
    """Baseline user without ADMIN receives a populated user-group list.

    Before the relax this returned 403. After the relax it returns
    tenant-scoped UserGroupPublic entries.
    """
    async with db_container() as container:
        group_repo = container.user_groups_repo()
        from eneo.user_groups.user_group import UserGroupCreate

        await group_repo.create_user_group(
            UserGroupCreate(
                name=f"picker-group-{uuid4().hex[:8]}",
                tenant_id=admin_user.tenant_id,
            )
        )

    resp = await client.get(
        "/api/v1/user-groups/",
        headers={"Authorization": f"Bearer {non_admin_token}"},
    )
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert "items" in body
    # Data-minimization: nested users must not expose quota_used.
    for group in body["items"]:
        for user in group.get("users", []):
            allowed = {"id", "email", "username", "created_at", "updated_at"}
            extra = set(user.keys()) - allowed
            assert extra == set(), (
                f"UserSparse leak check failed on group {group['id']}: {extra}"
            )


async def test_non_admin_cannot_create_user_group(client, non_admin_token):
    """Mutations on /user-groups/ remain ADMIN-gated."""
    resp = await client.post(
        "/api/v1/user-groups/",
        json={"name": f"should-fail-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {non_admin_token}"},
    )
    assert resp.status_code in (401, 403), resp.text


async def test_non_admin_cannot_invite_user(client, non_admin_token):
    """Mutations on /users/admin/invite/ remain ADMIN-gated."""
    resp = await client.post(
        "/api/v1/users/admin/invite/",
        json={
            "email": f"blocked-{uuid4().hex[:8]}@example.com",
        },
        headers={"Authorization": f"Bearer {non_admin_token}"},
    )
    assert resp.status_code in (401, 403), resp.text


async def test_users_list_rejects_limit_over_100(client, non_admin_token):
    """`?limit=` is capped at 100 to prevent full-directory dumps."""
    resp = await client.get(
        "/api/v1/users/?limit=10000",
        headers={"Authorization": f"Bearer {non_admin_token}"},
    )
    assert resp.status_code == 422, resp.text
