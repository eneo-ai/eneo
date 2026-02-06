"""Integration tests for API key CRUD, guardrails, rate limiting, and policy updates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest

from intric.main.config import get_settings, set_settings
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
async def regular_user_token(db_container, patch_auth_service_jwt, default_user):
    async with db_container() as container:
        user_repo = container.user_repo()
        auth_service = container.auth_service()
        user = await user_repo.add(
            UserAdd(
                email=f"regular-api-key-{uuid4().hex[:8]}@example.com",
                username=f"regular_api_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=default_user.tenant_id,
            )
        )
        token = auth_service.create_access_token_for_user(user)
    return token


async def _add_allowed_origin(db_container, tenant_id, origin: str):
    async with db_container() as container:
        repo = container.allowed_origin_repo()
        await repo.add_origin(origin=origin, tenant_id=tenant_id)


async def _create_space_and_assistant(
    client,
    *,
    bearer_token: str,
) -> tuple[str, str]:
    space_response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"api-key-space-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert space_response.status_code == 201, space_response.text
    space_id = space_response.json()["id"]

    assistant_response = await client.post(
        "/api/v1/assistants/",
        json={
            "name": f"api-key-assistant-{uuid4().hex[:8]}",
            "space_id": space_id,
        },
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert assistant_response.status_code == 200, assistant_response.text
    assistant_id = assistant_response.json()["id"]
    return space_id, assistant_id


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
async def test_legacy_user_api_key_endpoints_still_work(client, default_user_token):
    post_response = await client.post(
        "/api/v1/users/api-keys/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert post_response.status_code == 200, post_response.text
    post_payload = post_response.json()
    assert post_payload["key"].startswith("inp_")

    post_auth = await client.get(
        "/version",
        headers={"X-API-Key": post_payload["key"]},
    )
    assert post_auth.status_code == 200

    get_response = await client.get(
        "/api/v1/users/api-keys/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert get_response.status_code == 200, get_response.text
    get_payload = get_response.json()
    assert get_payload["key"].startswith("inp_")

    get_auth = await client.get(
        "/version",
        headers={"X-API-Key": get_payload["key"]},
    )
    assert get_auth.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_legacy_assistant_api_key_endpoint_still_works(
    client, default_user_token
):
    assistants_response = await client.get(
        "/api/v1/assistants/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert assistants_response.status_code == 200, assistants_response.text
    assistants_payload = assistants_response.json()
    assistant_items = assistants_payload.get("items", [])
    if not assistant_items:
        pytest.skip("No assistants available in integration seed data.")

    assistant_id = assistant_items[0]["id"]
    legacy_response = await client.get(
        f"/api/v1/assistants/{assistant_id}/api-keys/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert legacy_response.status_code == 200, legacy_response.text
    payload = legacy_response.json()
    assert payload["key"].startswith("ina_")


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
    assert second.headers.get("X-RateLimit-Limit") == "1"
    assert second.headers.get("X-RateLimit-Remaining") == "0"
    retry_after = second.headers.get("Retry-After")
    assert retry_after is not None
    assert int(retry_after) > 0


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
async def test_creation_constraints_reflect_tenant_policy(
    client,
    default_user_token,
    regular_user_token,
):
    update_response = await client.patch(
        "/api/v1/admin/api-key-policy",
        json={
            "require_expiration": True,
            "max_expiration_days": 45,
            "max_rate_limit_override": 123,
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert update_response.status_code == 200, update_response.text

    admin_constraints = await client.get(
        "/api/v1/api-keys/creation-constraints",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert admin_constraints.status_code == 200, admin_constraints.text
    admin_payload = admin_constraints.json()
    assert admin_payload["require_expiration"] is True
    assert admin_payload["max_expiration_days"] == 45
    assert admin_payload["max_rate_limit"] == 123

    user_constraints = await client.get(
        "/api/v1/api-keys/creation-constraints",
        headers={"Authorization": f"Bearer {regular_user_token}"},
    )
    assert user_constraints.status_code == 200, user_constraints.text
    user_payload = user_constraints.json()
    assert user_payload == admin_payload


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
async def test_api_key_rejects_zero_rate_limit(client, default_user_token):
    response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Invalid Rate",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
            "rate_limit": 0,
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "invalid_request"
    assert "rate_limit" in payload["message"]


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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_api_key_management_flow(client, default_user_token):
    create_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Admin Flow Key",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_response.status_code == 201, create_response.text
    created_payload = create_response.json()
    key_id = created_payload["api_key"]["id"]

    list_response = await client.get(
        "/api/v1/admin/api-keys",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert list_response.status_code == 200, list_response.text
    assert key_id in {item["id"] for item in list_response.json()["items"]}

    get_response = await client.get(
        f"/api/v1/admin/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert get_response.status_code == 200, get_response.text
    assert get_response.json()["id"] == key_id

    suspend_response = await client.post(
        f"/api/v1/admin/api-keys/{key_id}/suspend",
        json={"reason_code": "security_concern", "reason_text": "Suspicious pattern"},
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert suspend_response.status_code == 200, suspend_response.text
    assert suspend_response.json()["state"] == "suspended"

    reactivate_response = await client.post(
        f"/api/v1/admin/api-keys/{key_id}/reactivate",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert reactivate_response.status_code == 200, reactivate_response.text
    assert reactivate_response.json()["state"] == "active"

    rotate_response = await client.post(
        f"/api/v1/admin/api-keys/{key_id}/rotate",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert rotate_response.status_code == 200, rotate_response.text
    rotated_payload = rotate_response.json()
    assert rotated_payload["secret"].startswith("sk_")
    assert rotated_payload["api_key"]["rotated_from_key_id"] == key_id

    revoke_response = await client.post(
        f"/api/v1/admin/api-keys/{key_id}/revoke",
        json={"reason_code": "admin_action", "reason_text": "Manual revoke"},
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert revoke_response.status_code == 200, revoke_response.text
    assert revoke_response.json()["state"] == "revoked"


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/admin/api-keys"),
        ("GET", "/api/v1/admin/api-key-policy"),
        ("PATCH", "/api/v1/admin/api-key-policy"),
    ],
)
async def test_admin_api_key_endpoints_require_auth(client, method: str, path: str):
    payload = {"require_expiration": True} if method == "PATCH" else None
    response = await client.request(method, path, json=payload)
    assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_api_key_endpoints_reject_non_admin(
    client, default_user_token, regular_user_token
):
    create_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Admin Authz Key",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_response.status_code == 201, create_response.text
    key_id = create_response.json()["api_key"]["id"]

    list_response = await client.get(
        "/api/v1/admin/api-keys",
        headers={"Authorization": f"Bearer {regular_user_token}"},
    )
    assert list_response.status_code == 403, list_response.text

    get_response = await client.get(
        f"/api/v1/admin/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {regular_user_token}"},
    )
    assert get_response.status_code == 403, get_response.text

    policy_response = await client.patch(
        "/api/v1/admin/api-key-policy",
        json={"require_expiration": True},
        headers={"Authorization": f"Bearer {regular_user_token}"},
    )
    assert policy_response.status_code == 403, policy_response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_user_list_pagination_and_filtering(client, default_user_token):
    keys_to_create = [
        {
            "name": "Paged SK 1",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
        },
        {
            "name": "Paged SK 2",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
        },
        {
            "name": "Paged PK",
            "key_type": "pk_",
            "permission": "read",
            "scope_type": "tenant",
            "allowed_origins": ["http://localhost:3000"],
        },
    ]
    for payload in keys_to_create:
        response = await client.post(
            "/api/v1/api-keys",
            json=payload,
            headers={"Authorization": f"Bearer {default_user_token}"},
        )
        assert response.status_code == 201, response.text

    page_one = await client.get(
        "/api/v1/api-keys?limit=1",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert page_one.status_code == 200, page_one.text
    page_one_payload = page_one.json()
    assert len(page_one_payload["items"]) == 1
    assert page_one_payload["total_count"] >= 3
    assert page_one_payload["next_cursor"] is not None

    page_two = await client.get(
        f"/api/v1/api-keys?limit=1&cursor={page_one_payload['next_cursor']}",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert page_two.status_code == 200, page_two.text
    assert len(page_two.json()["items"]) == 1

    filtered = await client.get(
        "/api/v1/api-keys?key_type=pk_",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert filtered.status_code == 200, filtered.text
    filtered_items = filtered.json()["items"]
    assert filtered_items
    assert all(item["key_type"] == "pk_" for item in filtered_items)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_non_admin_list_total_count_is_null(client, regular_user_token):
    list_response = await client.get(
        "/api/v1/api-keys",
        headers={"Authorization": f"Bearer {regular_user_token}"},
    )
    assert list_response.status_code == 200, list_response.text
    payload = list_response.json()
    assert payload["total_count"] is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_list_filtering_and_total_count(client, default_user_token):
    create_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Admin Filter Key",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_response.status_code == 201, create_response.text
    key_id = create_response.json()["api_key"]["id"]

    filtered = await client.get(
        "/api/v1/admin/api-keys?key_type=sk_&state=active&limit=2",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert filtered.status_code == 200, filtered.text
    payload = filtered.json()
    assert payload["total_count"] >= len(payload["items"])
    assert any(item["id"] == key_id for item in payload["items"])
    assert all(item["key_type"] == "sk_" for item in payload["items"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sk_guardrail_rejects_malformed_forwarded_ip(client, default_user_token):
    settings = get_settings()
    patched = settings.model_copy(update={"trusted_proxy_count": 1})
    set_settings(patched)
    try:
        create_response = await client.post(
            "/api/v1/api-keys",
            json={
                "name": "Malformed XFF Key",
                "key_type": "sk_",
                "permission": "read",
                "scope_type": "tenant",
                "allowed_ips": ["203.0.113.0/24"],
            },
            headers={"Authorization": f"Bearer {default_user_token}"},
        )
        assert create_response.status_code == 201, create_response.text
        secret = create_response.json()["secret"]

        response = await client.get(
            "/version",
            headers={
                "X-API-Key": secret,
                "X-Forwarded-For": "not_an_ip, 10.0.0.1",
            },
        )
        assert response.status_code == 403
        assert response.json()["code"] == "ip_not_allowed"
    finally:
        set_settings(settings)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pk_guardrail_allows_ipv6_localhost_origin(client, default_user_token):
    create_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "IPv6 Localhost PK",
            "key_type": "pk_",
            "permission": "read",
            "scope_type": "tenant",
            "allowed_origins": ["http://localhost:5173"],
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_response.status_code == 201, create_response.text
    secret = create_response.json()["secret"]

    response = await client.get(
        "/version",
        headers={"X-API-Key": secret, "Origin": "http://[::1]:5173"},
    )
    assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lifecycle_negative_paths(client, default_user_token):
    create_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Lifecycle Negative Key",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_response.status_code == 201, create_response.text
    key_id = create_response.json()["api_key"]["id"]

    revoke_response = await client.post(
        f"/api/v1/api-keys/{key_id}/revoke",
        json={"reason_code": "security_concern"},
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert revoke_response.status_code == 200, revoke_response.text

    suspend_after_revoke = await client.post(
        f"/api/v1/api-keys/{key_id}/suspend",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert suspend_after_revoke.status_code == 400
    assert suspend_after_revoke.json()["code"] == "invalid_request"

    reactivate_after_revoke = await client.post(
        f"/api/v1/api-keys/{key_id}/reactivate",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert reactivate_after_revoke.status_code == 400
    assert reactivate_after_revoke.json()["code"] == "invalid_request"

    rotate_after_revoke = await client.post(
        f"/api/v1/api-keys/{key_id}/rotate",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert rotate_after_revoke.status_code == 401
    assert rotate_after_revoke.json()["code"] == "invalid_api_key"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_max_rate_limit_override_enforced_on_create_and_update(
    client,
    default_user_token,
):
    policy_response = await client.patch(
        "/api/v1/admin/api-key-policy",
        json={"max_rate_limit_override": 100},
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert policy_response.status_code == 200, policy_response.text

    create_unlimited = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Unlimited Blocked",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
            "rate_limit": -1,
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_unlimited.status_code == 400
    assert create_unlimited.json()["code"] == "invalid_request"

    create_exceeding = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Exceeding Blocked",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
            "rate_limit": 101,
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_exceeding.status_code == 400
    assert create_exceeding.json()["code"] == "invalid_request"

    create_valid = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Cap Valid",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
            "rate_limit": 100,
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_valid.status_code == 201, create_valid.text
    key_id = create_valid.json()["api_key"]["id"]

    update_unlimited = await client.patch(
        f"/api/v1/api-keys/{key_id}",
        json={"rate_limit": -1},
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert update_unlimited.status_code == 400
    assert update_unlimited.json()["code"] == "invalid_request"

    update_exceeding = await client.patch(
        f"/api/v1/api-keys/{key_id}",
        json={"rate_limit": 1000},
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert update_exceeding.status_code == 400
    assert update_exceeding.json()["code"] == "invalid_request"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rotate_preserves_resource_permissions(client, default_user_token):
    requested_permissions = {
        "assistants": "read",
        "apps": "write",
        "spaces": "none",
        "knowledge": "read",
    }
    create_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Rotate Resource Permissions",
            "key_type": "sk_",
            "permission": "write",
            "scope_type": "tenant",
            "resource_permissions": requested_permissions,
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_response.status_code == 201, create_response.text
    key_id = create_response.json()["api_key"]["id"]

    rotate_response = await client.post(
        f"/api/v1/api-keys/{key_id}/rotate",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert rotate_response.status_code == 200, rotate_response.text
    rotated_payload = rotate_response.json()
    assert rotated_payload["api_key"]["resource_permissions"] == requested_permissions


@pytest.mark.integration
@pytest.mark.asyncio
async def test_method_aware_guard_blocks_write_key_on_app_run_delete(
    client,
    default_user_token,
):
    key_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "App Run Delete Write Key",
            "key_type": "sk_",
            "permission": "write",
            "scope_type": "tenant",
            "resource_permissions": {
                "assistants": "none",
                "apps": "write",
                "spaces": "none",
                "knowledge": "none",
            },
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert key_response.status_code == 201, key_response.text
    secret = key_response.json()["secret"]

    response = await client.delete(
        f"/api/v1/app-runs/{uuid4()}/",
        headers={"X-API-Key": secret},
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "insufficient_resource_permission"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_method_aware_guard_allows_read_override_for_group_semantic_search(
    client,
    default_user_token,
):
    key_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Group Search Read Override Key",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
            "resource_permissions": {
                "assistants": "none",
                "apps": "none",
                "spaces": "none",
                "knowledge": "read",
            },
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert key_response.status_code == 201, key_response.text
    secret = key_response.json()["secret"]

    response = await client.post(
        f"/api/v1/groups/{uuid4()}/searches/",
        json={"search_string": "hello"},
        headers={"X-API-Key": secret},
    )
    # The endpoint should not fail due to method-aware resource guard.
    # Unknown group ids should fail deeper in the stack (typically 404).
    assert not (
        response.status_code == 403
        and response.json().get("code") == "insufficient_resource_permission"
    ), response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_method_aware_guard_blocks_read_key_on_assistant_session_create(
    client, default_user_token
):
    _, assistant_id = await _create_space_and_assistant(
        client,
        bearer_token=default_user_token,
    )

    key_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Knowledge Read Key",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
            "resource_permissions": {
                "assistants": "none",
                "apps": "none",
                "spaces": "none",
                "knowledge": "read",
            },
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert key_response.status_code == 201, key_response.text
    secret = key_response.json()["secret"]

    create_session_response = await client.post(
        f"/api/v1/assistants/{assistant_id}/sessions/",
        json={"question": "hello", "stream": False},
        headers={"X-API-Key": secret},
    )
    assert create_session_response.status_code == 403, create_session_response.text
    assert (
        create_session_response.json()["code"] == "insufficient_resource_permission"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_method_aware_guard_blocks_write_key_on_assistant_delete(
    client, default_user_token
):
    _, assistant_id = await _create_space_and_assistant(
        client,
        bearer_token=default_user_token,
    )

    key_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Knowledge Write Key",
            "key_type": "sk_",
            "permission": "write",
            "scope_type": "tenant",
            "resource_permissions": {
                "assistants": "none",
                "apps": "none",
                "spaces": "none",
                "knowledge": "write",
            },
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert key_response.status_code == 201, key_response.text
    secret = key_response.json()["secret"]

    delete_response = await client.delete(
        f"/api/v1/assistants/{assistant_id}/",
        headers={"X-API-Key": secret},
    )
    assert delete_response.status_code == 403, delete_response.text
    assert delete_response.json()["code"] == "insufficient_resource_permission"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_method_aware_guard_allows_read_override_for_assistant_token_estimate(
    client, default_user_token
):
    _, assistant_id = await _create_space_and_assistant(
        client,
        bearer_token=default_user_token,
    )

    key_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": "Assistant Estimate Key",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
            "resource_permissions": {
                "assistants": "read",
                "apps": "none",
                "spaces": "none",
                "knowledge": "read",
            },
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert key_response.status_code == 201, key_response.text
    secret = key_response.json()["secret"]

    estimate_response = await client.post(
        f"/api/v1/assistants/{assistant_id}/token-estimate",
        json={"text": "hello world"},
        headers={"X-API-Key": secret},
    )
    assert estimate_response.status_code == 200, estimate_response.text
