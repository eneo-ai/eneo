"""Integration tests for API key tenant isolation (TDD).

These tests validate that API key management endpoints never leak keys
across tenant boundaries.
"""

from __future__ import annotations

import psycopg2
import pytest

from init_db import add_tenant_user


@pytest.fixture
async def default_user_token(db_container, patch_auth_service_jwt):
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.get_user_by_email("test@example.com")
        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(user)
    return token


@pytest.fixture
async def second_tenant_user(db_container, test_settings):
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )

    add_tenant_user(
        conn,
        tenant_name="test_tenant_2",
        quota_limit=1000000,
        user_name="test_user_2",
        user_email="test2@example.com",
        user_password="test_password",
    )
    conn.close()

    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.get_user_by_email("test2@example.com")
    return user


@pytest.fixture
async def second_tenant_token(db_container, patch_auth_service_jwt, second_tenant_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(second_tenant_user)
    return token


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_key_tenant_isolation_for_management_endpoints(
    client,
    default_user_token: str,
    second_tenant_token: str,
):
    create_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Tenant One Key",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_response.status_code == 201, (
        f"Expected 201, got {create_response.status_code}: {create_response.text}"
    )
    created = create_response.json()["api_key"]
    key_id = created["id"]

    list_response = await client.get(
        "/api/v1/api-keys",
        headers={"Authorization": f"Bearer {second_tenant_token}"},
    )
    assert list_response.status_code == 200, (
        f"Expected 200, got {list_response.status_code}: {list_response.text}"
    )
    list_payload = list_response.json()
    assert key_id not in {item["id"] for item in list_payload["items"]}

    get_response = await client.get(
        f"/api/v1/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {second_tenant_token}"},
    )
    assert get_response.status_code == 404
    assert get_response.json() == {
        "code": "resource_not_found",
        "message": "API key not found.",
    }

    patch_response = await client.patch(
        f"/api/v1/api-keys/{key_id}",
        json={"name": "New Name"},
        headers={"Authorization": f"Bearer {second_tenant_token}"},
    )
    assert patch_response.status_code == 404
    assert patch_response.json() == {
        "code": "resource_not_found",
        "message": "API key not found.",
    }

    revoke_response = await client.post(
        f"/api/v1/api-keys/{key_id}/revoke",
        json={"reason_code": "security_concern"},
        headers={"Authorization": f"Bearer {second_tenant_token}"},
    )
    assert revoke_response.status_code == 404
    assert revoke_response.json() == {
        "code": "resource_not_found",
        "message": "API key not found.",
    }
