"""Route-level integration tests for POST /api/v1/spaces/ permission gating.

These tests lock in the behavior around the unify-roles-system PR:

  * User tokens must pass the `shared_spaces` role-permission gate.
    Users who lack it (no roles, or a role without the permission) get 403.
  * Service API keys are explicitly rejected on POST with a 403 + clear
    message. Reason: space creation always provisions a default assistant
    with `user_id = current_user.id`, but a service-key synthetic user
    has no row in `users`. Allowing service keys through would surface as
    a confusing 500 (FK violation on `assistants_users_fkey`). Service keys
    remain allowed on PATCH/DELETE (they operate on an existing space
    whose default assistant already has a valid `user_id`).

Run with:
    uv run pytest tests/integration/test_space_create_permissions.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from intric.main.models import ModelId
from intric.roles.role import RoleCreate
from intric.users.user import UserAdd, UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def admin_token(db_container, admin_user, patch_auth_service_jwt):
    """JWT token for the default admin user (test@example.com)."""
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(admin_user)


@pytest.fixture
async def no_role_user(db_container, admin_user):
    """Create a user with ZERO roles in the admin user's tenant.

    Uses `user_repo.add(...)` directly — the admin-facing service path
    auto-assigns the tenant's default role when `roles=[]`, which would
    hide what we're testing here (a zero-permissions user hitting the
    role gate).
    """
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.add(
            UserAdd(
                email=f"no-role-{uuid4().hex[:8]}@example.com",
                username=f"no_role_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[],
            )
        )
        # Pin the premise: if a future refactor adds auto-assignment of
        # the default role into user_repo.add, this test would silently
        # start passing for the wrong reason.
        assert len(user.roles) == 0, (
            f"no_role_user fixture must yield a user with zero roles, got "
            f"{[r.name for r in user.roles]}"
        )
    return user


@pytest.fixture
async def no_role_user_token(db_container, patch_auth_service_jwt, no_role_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(no_role_user)


@pytest.fixture
async def role_without_shared_spaces(db_container, admin_user):
    """Create a tenant role that has no `shared_spaces` permission."""
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
    """User whose only role lacks `shared_spaces` — POST should 403."""
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.add(
            UserAdd(
                email=f"gated-{uuid4().hex[:8]}@example.com",
                username=f"gated_{uuid4().hex[:8]}",
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_tenant_write_service_key(client, *, admin_token: str) -> str:
    """Create a tenant-scope ownership=service key with write permission.

    Returns the secret (for X-API-Key). Requires admin-token caller because
    only admins may create ownership=service keys.
    """
    expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    resp = await client.post(
        "/api/v1/api-keys",
        json={
            "name": f"svc-space-{uuid4().hex[:8]}",
            "key_type": "sk_",
            "permission": "write",
            "scope_type": "tenant",
            "ownership": "service",
            "expires_at": expires_at,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["secret"]


async def _post_space(client, *, headers: dict[str, str]):
    return await client.post(
        "/api/v1/spaces/",
        json={"name": f"space-{uuid4().hex[:8]}"},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_admin_user_can_create_space(client, admin_token):
    """Baseline: admin has shared_spaces, so POST /spaces succeeds."""
    resp = await _post_space(client, headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"].startswith("space-")


async def test_service_key_cannot_create_space(client, admin_token):
    """Service keys are rejected on POST with a 403 that names the reason.

    Not just a role-gate coincidence: even if a future change alters the
    shared_spaces permission model, the service-key path must stay blocked
    here — the default-assistant FK on users.id would surface as a 500
    otherwise. Ownership operations (PATCH/DELETE) are still allowed.
    """
    secret = await _create_tenant_write_service_key(client, admin_token=admin_token)
    resp = await _post_space(client, headers={"X-API-Key": secret})
    assert resp.status_code == 403, resp.text
    assert "service" in resp.text.lower()


async def test_user_with_no_roles_cannot_create_space(client, no_role_user_token):
    """A user with zero roles has zero permissions → 403 on POST /spaces."""
    resp = await _post_space(
        client, headers={"Authorization": f"Bearer {no_role_user_token}"}
    )
    assert resp.status_code == 403, resp.text


async def test_user_without_shared_spaces_permission_cannot_create_space(
    client, gated_user_token
):
    """User whose role lacks `shared_spaces` → 403 on POST /spaces.

    This is the central hook for the Swedish-customer requirement: admins
    can remove `shared_spaces` from a tenant role and immediately gate
    who can create shared spaces.
    """
    resp = await _post_space(
        client, headers={"Authorization": f"Bearer {gated_user_token}"}
    )
    assert resp.status_code == 403, resp.text
