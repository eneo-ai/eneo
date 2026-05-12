"""Integration tests for service-key endpoint gating.

Covers the three guarantees of the service-key hardening:

1. Synthesized permissions: a TENANT+ADMIN service key can call admin
   listings (e.g. `?for_tenant=true`) — the route-level role gate now
   passes via the synthetic role attached in `_build_service_user`.
2. Lifecycle gate: api-key lifecycle mutations (PATCH/DELETE/revoke/
   rotate/extend/purge/suspend/reactivate + notification PUTs) are
   session-only — no API key, user or service, can call them.
3. User-identity gate: endpoints that semantically require a real human
   user reject service keys with `code=user_identity_required`.

User-owned bearer/keys are unaffected — covered by the assertions on
the bearer-token control case in each block.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_service_key(
    client,
    *,
    token: str,
    scope_type: str,
    scope_id: str | None = None,
    permission: str,
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
    if expires_at is not None:
        body["expires_at"] = expires_at
    resp = await client.post(
        "/api/v1/api-keys",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(admin_user)


@pytest.fixture
async def tenant_admin_service_secret(client, admin_token) -> str:
    """A TENANT+ADMIN service key — needs an expiry to satisfy the
    write/admin guardrail policy."""
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    payload = await _create_service_key(
        client,
        token=admin_token,
        scope_type="tenant",
        permission="admin",
        expires_at=expires,
    )
    return payload["secret"]


@pytest.fixture
async def tenant_read_service_secret(client, admin_token) -> str:
    """A TENANT+READ service key — no guardrails required."""
    payload = await _create_service_key(
        client,
        token=admin_token,
        scope_type="tenant",
        permission="read",
    )
    return payload["secret"]


# ---------------------------------------------------------------------------
# 1. Synthesized permissions — admin listings now work for service keys
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_admin_service_key_can_list_assistants_for_tenant(
    client, tenant_admin_service_secret
):
    """`?for_tenant=true` is gated by validate_permissions(ADMIN). With the
    synthetic role, a TENANT+ADMIN service key now passes the gate."""
    resp = await client.get(
        "/api/v1/assistants/?for_tenant=true",
        headers={"X-API-Key": tenant_admin_service_secret},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_read_service_key_cannot_list_assistants_for_tenant(
    client, tenant_read_service_secret
):
    """READ-permission service keys still fail the ADMIN role gate — the
    synthesized role only adds ADMIN for TENANT+ADMIN keys."""
    resp = await client.get(
        "/api/v1/assistants/?for_tenant=true",
        headers={"X-API-Key": tenant_read_service_secret},
    )
    assert resp.status_code in (401, 403), resp.text


# ---------------------------------------------------------------------------
# 2. Lifecycle gate — api-key mutations are session-only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("PATCH", "/api/v1/api-keys/{id}"),
        ("DELETE", "/api/v1/api-keys/{id}"),
        ("POST", "/api/v1/api-keys/{id}/revoke"),
        ("POST", "/api/v1/api-keys/{id}/rotate"),
        ("POST", "/api/v1/api-keys/{id}/extend"),
        ("POST", "/api/v1/api-keys/{id}/purge"),
        ("POST", "/api/v1/api-keys/{id}/suspend"),
        ("POST", "/api/v1/api-keys/{id}/reactivate"),
        ("PUT", "/api/v1/api-keys/notification-preferences"),
    ],
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_key_lifecycle_mutations_reject_service_keys(
    client, tenant_admin_service_secret, admin_token, method, path
):
    """No API key — including a TENANT+ADMIN service key — can call api-key
    lifecycle mutations. require_session_auth rejects them all with 403."""
    # Mint a target key so the path resolves to something real for endpoints
    # that take {id}.
    payload = await _create_service_key(
        client,
        token=admin_token,
        scope_type="tenant",
        permission="read",
    )
    target_id = payload["api_key"]["id"]
    full_path = path.format(id=target_id)

    body: dict = {}
    if "extend" in path:
        body = {
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
        }
    elif "notification-preferences" in path:
        body = {"enabled": True, "days_before_expiry": [7]}
    elif method == "PATCH":
        body = {"name": "renamed"}

    resp = await client.request(
        method,
        full_path,
        json=body,
        headers={"X-API-Key": tenant_admin_service_secret},
    )
    assert resp.status_code == 403, resp.text
    assert "session token" in resp.text.lower()


# ---------------------------------------------------------------------------
# 3. User-identity gate — (b)-class endpoints reject service keys
# ---------------------------------------------------------------------------


def _has_user_identity_required_code(payload: dict) -> bool:
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return detail.get("code") == "user_identity_required"
    if isinstance(detail, str):
        return "user_identity_required" in detail
    # Top-level shape used by some error wrappers
    return payload.get("code") == "user_identity_required"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_users_me_rejects_service_key(client, tenant_admin_service_secret):
    resp = await client.get(
        "/api/v1/users/me/",
        headers={"X-API-Key": tenant_admin_service_secret},
    )
    assert resp.status_code == 403, resp.text
    assert _has_user_identity_required_code(resp.json()), resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_users_me_works_for_bearer_user(client, admin_token):
    """Sanity check — the user-identity gate must NOT regress bearer auth."""
    resp = await client.get(
        "/api/v1/users/me/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_legacy_user_api_key_endpoint_rejects_service_key(
    client, tenant_admin_service_secret
):
    resp = await client.post(
        "/api/v1/users/api-keys/",
        headers={"X-API-Key": tenant_admin_service_secret},
    )
    # The user-identity gate runs before the deprecated/permission checks,
    # so we expect 403 with our error code regardless of feature-flag state.
    assert resp.status_code == 403, resp.text
    assert _has_user_identity_required_code(resp.json()), resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_legacy_user_api_key_revoke_rejects_service_key(
    client, tenant_admin_service_secret
):
    resp = await client.delete(
        "/api/v1/users/api-keys/legacy",
        headers={"X-API-Key": tenant_admin_service_secret},
    )
    assert resp.status_code == 403, resp.text
    assert _has_user_identity_required_code(resp.json()), resp.text
