"""Integration tests for API key CRUD, guardrails, rate limiting, and policy updates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from intric.main.config import get_settings, set_settings


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


async def _add_allowed_origin(db_container, tenant_id, origin: str):
    async with db_container() as container:
        repo = container.allowed_origin_repo()
        await repo.add_origin(origin=origin, tenant_id=tenant_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_key_crud_flow(client, default_user_token):
    create_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Test Key",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_response.status_code == 201, create_response.text
    payload = create_response.json()
    assert payload["secret"].startswith("sk_")
    key_id = payload["api_key"]["id"]

    list_response = await client.get(
        "/api/v1/api-keys",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert key_id in {item["id"] for item in items}

    update_response = await client.patch(
        f"/api/v1/api-keys/{key_id}",
        json={"name": "Renamed Key"},
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Renamed Key"

    revoke_response = await client.post(
        f"/api/v1/api-keys/{key_id}/revoke",
        json={"reason_code": "security_concern", "reason_text": "Compromised"},
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert revoke_response.status_code == 200
    assert revoke_response.json()["state"] == "revoked"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pk_origin_guardrail(
    client, db_container, default_user, default_user_token
):
    await _add_allowed_origin(
        db_container, default_user.tenant_id, "https://app.example.com"
    )

    create_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Widget Key",
            "key_type": "pk_",
            "permission": "read",
            "scope_type": "tenant",
            "allowed_origins": ["https://app.example.com"],
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_response.status_code == 201, create_response.text
    secret = create_response.json()["secret"]

    ok_response = await client.get(
        "/version",
        headers={
            "X-API-Key": secret,
            "Origin": "https://app.example.com",
        },
    )
    assert ok_response.status_code == 200

    deny_response = await client.get(
        "/version",
        headers={
            "X-API-Key": secret,
            "Origin": "https://evil.example.com",
        },
    )
    assert deny_response.status_code == 403
    assert deny_response.json()["code"] == "origin_not_allowed"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sk_ip_guardrail(client, default_user_token):
    settings = get_settings()
    patched = settings.model_copy(update={"trusted_proxy_count": 1})
    set_settings(patched)
    try:
        create_response = await client.post(
            "/api/v1/api-keys",
            json={
                "name": "Server Key",
                "key_type": "sk_",
                "permission": "read",
                "scope_type": "tenant",
                "allowed_ips": ["203.0.113.0/24"],
            },
            headers={"Authorization": f"Bearer {default_user_token}"},
        )
        assert create_response.status_code == 201, create_response.text
        secret = create_response.json()["secret"]

        ok_response = await client.get(
            "/version",
            headers={
                "X-API-Key": secret,
                "X-Forwarded-For": "203.0.113.10, 10.0.0.1",
            },
        )
        assert ok_response.status_code == 200

        deny_response = await client.get(
            "/version",
            headers={
                "X-API-Key": secret,
                "X-Forwarded-For": "198.51.100.10, 10.0.0.1",
            },
        )
        assert deny_response.status_code == 403
        assert deny_response.json()["code"] == "ip_not_allowed"
    finally:
        set_settings(settings)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rate_limit_enforced(client, default_user_token):
    create_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Rate Limited",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
            "rate_limit": 1,
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_response.status_code == 201
    secret = create_response.json()["secret"]

    first = await client.get(
        "/version",
        headers={"X-API-Key": secret},
    )
    assert first.status_code == 200

    second = await client.get(
        "/version",
        headers={"X-API-Key": secret},
    )
    assert second.status_code == 429
    assert second.json()["code"] == "rate_limit_exceeded"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_api_key_policy_update(
    client,
    default_user_token,
):
    response = await client.patch(
        "/api/v1/admin/api-key-policy",
        json={"require_expiration": True, "max_expiration_days": 90},
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["require_expiration"] is True
    assert payload["max_expiration_days"] == 90


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_key_rejects_missing_origins(client, default_user_token):
    response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Invalid Widget",
            "key_type": "pk_",
            "permission": "read",
            "scope_type": "tenant",
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_key_auth_performance_smoke(
    client,
    default_user_token,
):
    create_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Perf Key",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_response.status_code == 201
    secret = create_response.json()["secret"]

    start = datetime.now(timezone.utc)
    for _ in range(10):
        response = await client.get(
            "/version",
            headers={"X-API-Key": secret},
        )
        assert response.status_code == 200

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    assert elapsed < 5.0, f"Auth path too slow: {elapsed:.2f}s for 10 calls"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_key_expired_denied(client, default_user_token):
    expired_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    create_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Expired Key",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
            "expires_at": expired_at,
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_response.status_code == 201, create_response.text
    secret = create_response.json()["secret"]

    response = await client.get(
        "/version",
        headers={"X-API-Key": secret},
    )
    assert response.status_code == 401
    payload = response.json()
    assert payload["code"] == "invalid_api_key"
    assert "expired" in payload["message"].lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_key_suspended_denied(client, default_user_token):
    create_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Suspended Key",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_response.status_code == 201, create_response.text
    payload = create_response.json()
    secret = payload["secret"]
    key_id = payload["api_key"]["id"]

    suspend_response = await client.post(
        f"/api/v1/api-keys/{key_id}/suspend",
        json={"reason_code": "security_concern", "reason_text": "Risk detected"},
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert suspend_response.status_code == 200

    response = await client.get(
        "/version",
        headers={"X-API-Key": secret},
    )
    assert response.status_code == 401
    payload = response.json()
    assert payload["code"] == "invalid_api_key"
    assert "suspended" in payload["message"].lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_invalid_api_key_denied(client):
    response = await client.get(
        "/version",
        headers={"X-API-Key": "sk_invalid_123456"},
    )
    assert response.status_code == 401
    payload = response.json()
    assert payload["code"] == "invalid_api_key"
