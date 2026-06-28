"""Route-level integration tests for shared-space VIEW access.

These lock in the post-narrowing semantics (April 2026): `shared_spaces`
gates SPACE CREATION only. Viewing and membership are governed by
`SpaceActor` direct/group membership — independent of the tenant-level
permission.

Coverage:

  * Positive: a user whose role LACKS `shared_spaces` but who is a direct
    member of a shared space can GET that space (200) and see it in the
    GET /spaces/ list. This is the semantic Cagri asked for — membership
    is the authoritative viewer gate.
  * Negative: a non-member still cannot see the space. Permission alone
    does not grant access; membership is still required.

Run with:
    uv run pytest tests/integration/test_space_view_membership.py -v
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.main.models import ModelId
from eneo.roles.role import RoleCreate
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.users.user import UserAdd, UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def admin_token(db_container, admin_user, patch_auth_service_jwt):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(admin_user)


@pytest.fixture
async def role_without_shared_spaces(db_container, admin_user):
    async with db_container() as container:
        role_repo = container.role_repo()
        role = await role_repo.create_role(
            RoleCreate(
                name=f"no-ss-role-{uuid4().hex[:8]}",
                permissions=[],
                tenant_id=admin_user.tenant_id,
            )
        )
    return role


@pytest.fixture
async def gated_user(db_container, admin_user, role_without_shared_spaces):
    """User whose only role lacks `shared_spaces`."""
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.add(
            UserAdd(
                email=f"view-gated-{uuid4().hex[:8]}@example.com",
                username=f"view_gated_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role_without_shared_spaces.id)],
            )
        )
    return user


@pytest.fixture
async def gated_user_token(db_container, patch_auth_service_jwt, gated_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(gated_user)


async def _create_shared_space(client, *, admin_token: str) -> str:
    resp = await client.post(
        "/api/v1/spaces/",
        json={"name": f"view-space-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _add_space_member(
    db_container,
    *,
    space_id: str,
    user_id: UUID,
    role: str = SpaceRoleValue.VIEWER.value,
) -> None:
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.text(
                """
                INSERT INTO spaces_users (space_id, user_id, role)
                VALUES (:space_id, :user_id, :role)
                ON CONFLICT DO NOTHING
                """
            ),
            {"space_id": space_id, "user_id": str(user_id), "role": role},
        )
        await session.commit()


async def test_member_without_shared_spaces_permission_can_see_space(
    client, db_container, admin_token, gated_user, gated_user_token
):
    """Central regression for the narrowed semantic.

    A user whose role has no `shared_spaces` permission, but who has been
    added as a direct member of a shared space, MUST be able to view that
    space. Membership is authoritative; the permission only gates creation.
    """
    space_id = await _create_shared_space(client, admin_token=admin_token)
    await _add_space_member(db_container, space_id=space_id, user_id=gated_user.id)

    detail_resp = await client.get(
        f"/api/v1/spaces/{space_id}/",
        headers={"Authorization": f"Bearer {gated_user_token}"},
    )
    assert detail_resp.status_code == 200, detail_resp.text

    list_resp = await client.get(
        "/api/v1/spaces/",
        headers={"Authorization": f"Bearer {gated_user_token}"},
    )
    assert list_resp.status_code == 200, list_resp.text
    ids = {s["id"] for s in list_resp.json()["items"]}
    assert space_id in ids


async def test_non_member_without_shared_spaces_permission_cannot_see_space(
    client, admin_token, gated_user_token
):
    """Negative control for the positive case above.

    A user without `shared_spaces` AND without membership still cannot
    access the space — permission alone was never sufficient; membership
    alone is what grants access.
    """
    space_id = await _create_shared_space(client, admin_token=admin_token)

    detail_resp = await client.get(
        f"/api/v1/spaces/{space_id}/",
        headers={"Authorization": f"Bearer {gated_user_token}"},
    )
    assert detail_resp.status_code in (403, 404), detail_resp.text

    list_resp = await client.get(
        "/api/v1/spaces/",
        headers={"Authorization": f"Bearer {gated_user_token}"},
    )
    assert list_resp.status_code == 200, list_resp.text
    ids = {s["id"] for s in list_resp.json()["items"]}
    assert space_id not in ids
