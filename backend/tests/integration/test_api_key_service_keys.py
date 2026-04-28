"""Integration tests for service API key ownership.

Validates:
- Service keys survive owner deactivation/deletion/member removal
- Service keys still enforce scope
- Service key creation rejected for non-admins

Run with:
    uv run pytest tests/integration/test_api_key_service_keys.py -v -s
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.users.user import UserAdd, UserState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def default_user(db_container):
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.get_user_by_email("test@example.com")
    return user


@pytest.fixture
async def default_user_token(db_container, patch_auth_service_jwt, default_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(default_user)
    return token


@pytest.fixture
async def regular_user(db_container, default_user):
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.add(
            UserAdd(
                email=f"regular-svc-{uuid4().hex[:8]}@example.com",
                username=f"regular_svc_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=default_user.tenant_id,
            )
        )
    return user


@pytest.fixture
async def regular_user_token(db_container, patch_auth_service_jwt, regular_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(regular_user)
    return token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AUTH_ENDPOINT = "/api/v1/assistants/"


async def _create_space(client, *, token):
    resp = await client.post(
        "/api/v1/spaces/",
        json={"name": f"svc-space-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_service_key(
    client,
    *,
    token: str,
    scope_type: str = "tenant",
    scope_id: str | None = None,
    permission: str = "read",
    allowed_ips: list[str] | None = None,
    expires_at: str | None = None,
) -> dict:
    body: dict = {
        "name": f"svc-key-{uuid4().hex[:8]}",
        "key_type": "sk_",
        "permission": permission,
        "scope_type": scope_type,
        "ownership": "service",
    }
    if scope_id is not None:
        body["scope_id"] = scope_id
    if allowed_ips is not None:
        body["allowed_ips"] = allowed_ips
    if expires_at is not None:
        body["expires_at"] = expires_at
    resp = await client.post(
        "/api/v1/api-keys",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp


async def _deactivate_user(db_container, user_id: UUID):
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.text("UPDATE users SET state = 'inactive' WHERE id = :uid"),
            {"uid": str(user_id)},
        )
        await session.commit()


async def _delete_user(db_container, user_id: UUID):
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.text("DELETE FROM users WHERE id = :uid"),
            {"uid": str(user_id)},
        )
        await session.commit()


async def _remove_space_member(db_container, space_id: str, user_id: UUID):
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.text(
                "DELETE FROM spaces_users WHERE space_id = :sid AND user_id = :uid"
            ),
            {"sid": space_id, "uid": str(user_id)},
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_key_creation_rejected_for_non_admin(client, regular_user_token):
    """A user without Permission.API_KEYS cannot create service-owned keys.

    The role-level gate (require_permission(Permission.API_KEYS)) fires before
    the policy-level "service keys require admin" check, so the underlying
    rejection layer differs from earlier versions — but the security
    invariant (unprivileged user → 403) is unchanged.
    """
    resp = await _create_service_key(
        client,
        token=regular_user_token,
        scope_type="tenant",
        permission="read",
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_key_tenant_write_requires_guardrails(client, default_user_token):
    """Service tenant write/admin key without IP or expiry is rejected."""
    resp = await _create_service_key(
        client,
        token=default_user_token,
        scope_type="tenant",
        permission="write",
    )
    assert resp.status_code == 400, resp.text
    assert "IP allowlist or expiration" in resp.json()["message"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_key_tenant_write_accepted_with_expiry(
    client, default_user_token
):
    """Service tenant write key with expiration passes."""
    expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    resp = await _create_service_key(
        client,
        token=default_user_token,
        scope_type="tenant",
        permission="write",
        expires_at=expires,
    )
    assert resp.status_code == 201, resp.text
    key = resp.json()["api_key"]
    assert key["ownership"] == "service"
    assert key["owner_user_id"] is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_key_tenant_read_no_guardrails_needed(client, default_user_token):
    """Service tenant read key doesn't need IP/expiry guardrail."""
    resp = await _create_service_key(
        client,
        token=default_user_token,
        scope_type="tenant",
        permission="read",
    )
    assert resp.status_code == 201, resp.text
    key = resp.json()["api_key"]
    assert key["ownership"] == "service"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_key_survives_owner_deactivation(
    client, db_container, default_user, default_user_token
):
    """Service key continues to work after creator is deactivated."""
    # Create a service key (tenant read, no guardrail needed)
    resp = await _create_service_key(
        client,
        token=default_user_token,
        scope_type="tenant",
        permission="read",
    )
    assert resp.status_code == 201
    secret = resp.json()["secret"]

    # Verify key works
    probe = await client.get(
        _AUTH_ENDPOINT,
        headers={"X-API-Key": secret},
    )
    assert probe.status_code == 200, probe.text

    # Deactivate the creator
    await _deactivate_user(db_container, default_user.id)

    # Service key should still work
    probe2 = await client.get(
        _AUTH_ENDPOINT,
        headers={"X-API-Key": secret},
    )
    assert probe2.status_code == 200, (
        f"Service key should survive owner deactivation: {probe2.text}"
    )

    # Re-activate for cleanup
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.text("UPDATE users SET state = 'active' WHERE id = :uid"),
            {"uid": str(default_user.id)},
        )
        await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_key_survives_owner_deletion(
    client, db_container, default_user, default_user_token
):
    """Service key continues to work after creator is deleted (SET NULL)."""
    # Create a second admin user to be the creator
    async with db_container() as container:
        user_repo = container.user_repo()
        creator = await user_repo.add(
            UserAdd(
                email=f"creator-svc-{uuid4().hex[:8]}@example.com",
                username=f"creator_svc_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=default_user.tenant_id,
            )
        )
        # Make them admin
        session = container.session()
        await session.execute(
            sa.text(
                "INSERT INTO users_roles (user_id, role_id) "
                "SELECT :uid, id FROM roles "
                "WHERE name = 'Owner' AND tenant_id = :tid LIMIT 1"
            ),
            {"uid": str(creator.id), "tid": str(creator.tenant_id)},
        )

    # Re-fetch creator so permissions include the admin role
    async with db_container() as container:
        user_repo = container.user_repo()
        creator = await user_repo.get_user_by_id(creator.id)
        auth_service = container.auth_service()
        creator_token = auth_service.create_access_token_for_user(creator)

    # Create a service key under the creator
    resp = await _create_service_key(
        client,
        token=creator_token,
        scope_type="tenant",
        permission="read",
    )
    assert resp.status_code == 201, f"Creator failed to create service key: {resp.text}"
    secret = resp.json()["secret"]

    # Verify it works
    probe = await client.get(
        _AUTH_ENDPOINT,
        headers={"X-API-Key": secret},
    )
    assert probe.status_code == 200

    # Delete the creator — FK SET NULL should preserve the key
    await _delete_user(db_container, creator.id)

    # Service key should still work
    probe2 = await client.get(
        _AUTH_ENDPOINT,
        headers={"X-API-Key": secret},
    )
    assert probe2.status_code == 200, (
        f"Service key should survive owner deletion: {probe2.text}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_key_still_enforces_scope(client, default_user_token):
    """Service key with space scope cannot access resources in another space."""
    space_id = await _create_space(client, token=default_user_token)

    resp = await _create_service_key(
        client,
        token=default_user_token,
        scope_type="space",
        scope_id=space_id,
        permission="read",
    )
    assert resp.status_code == 201
    secret = resp.json()["secret"]

    # Create a different space
    other_space_id = await _create_space(client, token=default_user_token)

    # Try to access an assistant in the other space — should be denied by scope enforcement
    # First create an assistant in the other space
    asst_resp = await client.post(
        "/api/v1/assistants/",
        json={"name": f"test-asst-{uuid4().hex[:8]}", "space_id": other_space_id},
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert asst_resp.status_code == 200
    other_assistant_id = asst_resp.json()["id"]

    # Access with service key scoped to first space — should fail
    probe = await client.get(
        f"/api/v1/assistants/{other_assistant_id}/",
        headers={"X-API-Key": secret},
    )
    # Should be denied (403 scope mismatch or similar)
    assert probe.status_code in (401, 403), (
        f"Scope enforcement failed: {probe.status_code} {probe.text}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_key_space_scoped_can_read_space(client, default_user_token):
    """Space-scoped read service key can GET the space it's scoped to."""
    space_id = await _create_space(client, token=default_user_token)

    resp = await _create_service_key(
        client,
        token=default_user_token,
        scope_type="space",
        scope_id=space_id,
        permission="read",
    )
    assert resp.status_code == 201
    secret = resp.json()["secret"]

    probe = await client.get(
        f"/api/v1/spaces/{space_id}/",
        headers={"X-API-Key": secret},
    )
    assert probe.status_code == 200, (
        f"Space-scoped read key should access its own space: {probe.text}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_key_space_scoped_read_cannot_patch_space(
    client, default_user_token
):
    """Space-scoped read service key cannot PATCH the space (needs admin)."""
    space_id = await _create_space(client, token=default_user_token)

    resp = await _create_service_key(
        client,
        token=default_user_token,
        scope_type="space",
        scope_id=space_id,
        permission="read",
    )
    assert resp.status_code == 201
    secret = resp.json()["secret"]

    probe = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        json={"name": "should-fail"},
        headers={"X-API-Key": secret},
    )
    assert probe.status_code == 403, (
        f"Read key should not be able to PATCH space: {probe.status_code}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_key_space_scoped_write_cannot_patch_space(
    client, default_user_token
):
    """Space-scoped write service key maps to EDITOR — cannot edit space settings."""
    space_id = await _create_space(client, token=default_user_token)

    expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    resp = await _create_service_key(
        client,
        token=default_user_token,
        scope_type="space",
        scope_id=space_id,
        permission="write",
        expires_at=expires,
    )
    assert resp.status_code == 201
    secret = resp.json()["secret"]

    probe = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        json={"name": "should-fail"},
        headers={"X-API-Key": secret},
    )
    assert probe.status_code == 403, (
        f"Write key (EDITOR) should not be able to PATCH space: {probe.status_code}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_key_space_scoped_admin_can_patch_space(
    client, default_user_token
):
    """Space-scoped admin service key maps to ADMIN — can edit space settings."""
    space_id = await _create_space(client, token=default_user_token)

    expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    resp = await _create_service_key(
        client,
        token=default_user_token,
        scope_type="space",
        scope_id=space_id,
        permission="admin",
        expires_at=expires,
    )
    assert resp.status_code == 201
    secret = resp.json()["secret"]

    new_name = f"renamed-{uuid4().hex[:8]}"
    probe = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        json={"name": new_name},
        headers={"X-API-Key": secret},
    )
    assert probe.status_code == 200, (
        f"Admin key should be able to PATCH space: {probe.text}"
    )
    assert probe.json()["name"] == new_name


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_key_survives_member_removal(
    client, db_container, default_user, default_user_token
):
    """Space-scoped service key still works after creator is removed from space."""
    space_id = await _create_space(client, token=default_user_token)

    resp = await _create_service_key(
        client,
        token=default_user_token,
        scope_type="space",
        scope_id=space_id,
        permission="read",
    )
    assert resp.status_code == 201
    secret = resp.json()["secret"]

    # Verify key works
    probe = await client.get(
        f"/api/v1/spaces/{space_id}/",
        headers={"X-API-Key": secret},
    )
    assert probe.status_code == 200

    # Remove the creator from the space
    await _remove_space_member(db_container, space_id, default_user.id)

    # Service key should still work — it's not tied to the user's membership
    probe2 = await client.get(
        f"/api/v1/spaces/{space_id}/",
        headers={"X-API-Key": secret},
    )
    assert probe2.status_code == 200, (
        f"Service key should survive member removal: {probe2.text}"
    )

    # Re-add the user for cleanup
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.text(
                "INSERT INTO spaces_users (space_id, user_id, role) "
                "VALUES (:sid, :uid, 'admin') ON CONFLICT DO NOTHING"
            ),
            {"sid": space_id, "uid": str(default_user.id)},
        )
        await session.commit()
