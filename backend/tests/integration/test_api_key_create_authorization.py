"""Authorization tests for POST /api-keys.

Verifies the session-only + ``Permission.API_KEYS`` gate that replaced
the legacy ``ApiKeyPermission.ADMIN``-only guard. Two invariants:

1. Session callers must hold ``Permission.API_KEYS`` to mint a key.
2. API-key callers cannot mint keys at all — creation is UI-only.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from intric.users.user import UserAdd, UserState


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
async def user_without_api_keys_permission(db_container, default_user):
    """User with no role assigned — has zero Permission bits."""
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.add(
            UserAdd(
                email=f"no-api-keys-{uuid4().hex[:8]}@example.com",
                username=f"no_api_keys_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=default_user.tenant_id,
            )
        )
    return user


@pytest.fixture
async def user_without_api_keys_token(
    db_container, patch_auth_service_jwt, user_without_api_keys_permission
):
    async with db_container() as container:
        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(
            user_without_api_keys_permission
        )
    return token


@pytest.mark.integration
@pytest.mark.asyncio
async def test_owner_session_can_create_tenant_key(client, default_user_token):
    """Owner role carries Permission.API_KEYS post-migration."""
    response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Owner Key",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 201, response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_user_without_api_keys_permission_cannot_create(
    client, user_without_api_keys_token
):
    """Session call without Permission.API_KEYS → 403."""
    response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Should Fail",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
        },
        headers={"Authorization": f"Bearer {user_without_api_keys_token}"},
    )
    assert response.status_code == 403, response.text
    assert "api_keys" in response.json().get("detail", "").lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_key_caller_cannot_mint_new_key(client, default_user_token):
    """An admin-level v2 API key cannot bootstrap another key — UI only."""
    create_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Bootstrap Admin",
            "key_type": "sk_",
            "permission": "admin",
            "scope_type": "tenant",
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_response.status_code == 201, create_response.text
    secret = create_response.json()["secret"]

    spawn_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Spawned Key",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
        },
        headers={"X-API-Key": secret},
    )
    assert spawn_response.status_code == 403, spawn_response.text
    assert "session token" in spawn_response.json().get("detail", "").lower()
