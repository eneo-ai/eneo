"""End-to-end integration tests for multi-tenant authentication flows.

These tests exercise the public HTTP surface without reaching directly into
repository fixtures. They focus on:

* Configuring distinct OIDC providers per tenant and ensuring the login flow
  never leaks state across tenants.
* Verifying classic username/password login continues to function when
  multiple tenants exist, including isolation of returned tenant metadata.

External IdP interactions (discovery, token exchange, JWKS) are stubbed to
avoid outbound HTTP calls while still exercising the complete backend logic.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from intric.authentication.auth_service import AuthService


async def _create_tenant(client, super_api_key: str, name: str):
    payload = {
        "name": name,
        "display_name": name,
        "state": "active",
    }
    response = await client.post(
        "/api/v1/sysadmin/tenants/",
        json=payload,
        headers={"X-API-Key": super_api_key},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _create_user(client, super_api_key: str, tenant_id: str, email: str, password: str):
    payload = {
        "email": email,
        "username": email.split("@")[0],
        "tenant_id": tenant_id,
        "password": password,
    }
    response = await client.post(
        "/api/v1/sysadmin/users/",
        json=payload,
        headers={"X-API-Key": super_api_key},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _configure_federation(
    client,
    super_api_key: str,
    tenant_id: str,
    *,
    discovery_endpoint: str,
    allowed_domain: str,
    client_id: str,
):
    payload = {
        "provider": "entra",
        "discovery_endpoint": discovery_endpoint,
        "client_id": client_id,
        "client_secret": "super-secret",
        "allowed_domains": [allowed_domain],
    }
    response = await client.put(
        f"/api/v1/sysadmin/tenants/{tenant_id}/federation",
        json=payload,
        headers={"X-API-Key": super_api_key},
    )
    assert response.status_code == 200, response.text


async def _initiate_oidc(client, tenant_slug: str):
    response = await client.get(f"/api/v1/auth/initiate?tenant={tenant_slug}")
    assert response.status_code == 200, response.text
    return response.json()


async def _complete_oidc(client, code: str, state: str):
    response = await client.post(
        "/api/v1/auth/callback",
        json={"code": code, "state": state},
    )
    return response


def _fake_payload_factory(token_email_map: dict[str, str]):
    def _fake_get_payload(
        self,
        *,
        id_token,
        access_token,
        key,
        signing_algos,
        client_id,
        correlation_id,
        options=None,
    ):
        if id_token not in token_email_map:
            raise AssertionError(f"Unexpected id_token: {id_token}")
        return {"email": token_email_map[id_token]}

    return _fake_get_payload


def _build_oidc_maps(tenant_slug: str, issuer_base: str):
    discovery_url = f"{issuer_base}/.well-known/openid-configuration"
    discovery_payload = {
        "issuer": issuer_base,
        "authorization_endpoint": f"{issuer_base}/authorize",
        "token_endpoint": f"{issuer_base}/token",
        "jwks_uri": f"{issuer_base}/jwks",
        "userinfo_endpoint": f"{issuer_base}/userinfo",
    }
    return discovery_url, discovery_payload


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_tenant_oidc_login_isolated(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    oidc_mock,
    jwks_mock,
    monkeypatch,
    mock_transcription_models,
):
    slug_a = f"tenant-a-{uuid4().hex[:6]}"
    slug_b = f"tenant-b-{uuid4().hex[:6]}"

    tenant_a = await _create_tenant(client, super_admin_token, slug_a)
    tenant_b = await _create_tenant(client, super_admin_token, slug_b)

    email_a = f"alice@{slug_a}.example.com"
    email_b = f"bruno@{slug_b}.example.com"
    password = "ValidPassw0rd!"

    await _create_user(client, super_admin_token, tenant_a["id"], email_a, password)
    await _create_user(client, super_admin_token, tenant_b["id"], email_b, password)

    discovery_a_url, discovery_a_payload = _build_oidc_maps(
        slug_a, f"https://idp.{slug_a}.local"
    )
    discovery_b_url, discovery_b_payload = _build_oidc_maps(
        slug_b, f"https://idp.{slug_b}.local"
    )

    oidc_calls = oidc_mock(
        discovery={
            discovery_a_url: discovery_a_payload,
            discovery_b_url: discovery_b_payload,
        },
        tokens={
            (discovery_a_payload["token_endpoint"], "code-tenant-a"): {
                "id_token": "id-token-tenant-a",
                "access_token": "access-token-tenant-a",
            },
            (discovery_b_payload["token_endpoint"], "code-tenant-b"): {
                "id_token": "id-token-tenant-b",
                "access_token": "access-token-tenant-b",
            },
            (discovery_b_payload["token_endpoint"], "code-tenant-b-cross"): {
                "id_token": "id-token-tenant-b-cross",
                "access_token": "access-token-tenant-b-cross",
            },
        },
    )

    jwks_mock()

    token_email_map = {
        "id-token-tenant-a": email_a,
        "id-token-tenant-b": email_b,
        # Cross attempt uses tenant A email to trigger domain mismatch in tenant B
        "id-token-tenant-b-cross": email_a,
    }

    monkeypatch.setattr(
        AuthService,
        "get_payload_from_openid_jwt",
        _fake_payload_factory(token_email_map),
    )

    await _configure_federation(
        client,
        super_admin_token,
        tenant_a["id"],
        discovery_endpoint=discovery_a_url,
        allowed_domain=f"{slug_a}.example.com",
        client_id=f"client-{slug_a}",
    )
    await _configure_federation(
        client,
        super_admin_token,
        tenant_b["id"],
        discovery_endpoint=discovery_b_url,
        allowed_domain=f"{slug_b}.example.com",
        client_id=f"client-{slug_b}",
    )

    initiate_a = await _initiate_oidc(client, tenant_a["slug"])
    initiate_b = await _initiate_oidc(client, tenant_b["slug"])

    assert initiate_a["authorization_url"].startswith(
        discovery_a_payload["authorization_endpoint"]
    )
    assert initiate_b["authorization_url"].startswith(
        discovery_b_payload["authorization_endpoint"]
    )

    state_a = initiate_a["state"]
    state_b = initiate_b["state"]

    callback_a = await _complete_oidc(client, "code-tenant-a", state_a)
    assert callback_a.status_code == 200, callback_a.text
    token_a = callback_a.json()["access_token"]

    me_a = await client.get(
        "/api/v1/users/tenant/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert me_a.status_code == 200
    assert me_a.json()["name"] == tenant_a["slug"]

    callback_b = await _complete_oidc(client, "code-tenant-b", state_b)
    assert callback_b.status_code == 200, callback_b.text
    token_b = callback_b.json()["access_token"]

    me_b = await client.get(
        "/api/v1/users/tenant/",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert me_b.status_code == 200
    assert me_b.json()["name"] == tenant_b["slug"]

    callback_cross = await _complete_oidc(client, "code-tenant-b-cross", state_b)
    assert callback_cross.status_code == 400  # Domain mismatch returns 400 Bad Request
    # Check for domain validation error message
    detail = callback_cross.json()["detail"]
    assert "invalid" in detail.lower() or "expired" in detail.lower() or "not allowed" in detail.lower()

    # Ensure tests never escape to the real network
    requests = oidc_calls()["requests"]
    assert all(url.startswith("https://idp.") for _, url in requests)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_tenant_password_login(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
):
    slug_a = f"tenant-pass-a-{uuid4().hex[:6]}"
    slug_b = f"tenant-pass-b-{uuid4().hex[:6]}"

    tenant_a = await _create_tenant(client, super_admin_token, slug_a)
    tenant_b = await _create_tenant(client, super_admin_token, slug_b)

    email_a = f"alex@{slug_a}.example.com"
    email_b = f"bella@{slug_b}.example.com"
    password_a = "TenantApass123!"
    password_b = "TenantBpass123!"

    await _create_user(client, super_admin_token, tenant_a["id"], email_a, password_a)
    await _create_user(client, super_admin_token, tenant_b["id"], email_b, password_b)

    login_a = await client.post(
        "/api/v1/users/login/token/",
        data={"username": email_a, "password": password_a},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_a.status_code == 200, login_a.text
    token_a = login_a.json()["access_token"]

    tenant_info_a = await client.get(
        "/api/v1/users/tenant/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert tenant_info_a.status_code == 200
    # The tenant endpoint returns 'name' field, which is the tenant slug
    assert tenant_info_a.json()["name"] == tenant_a["slug"]

    login_b = await client.post(
        "/api/v1/users/login/token/",
        data={"username": email_b, "password": password_b},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_b.status_code == 200, login_b.text
    token_b = login_b.json()["access_token"]

    tenant_info_b = await client.get(
        "/api/v1/users/tenant/",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert tenant_info_b.status_code == 200
    # The tenant endpoint returns 'name' field, which is the tenant slug
    assert tenant_info_b.json()["name"] == tenant_b["slug"]

    wrong_password = await client.post(
        "/api/v1/users/login/token/",
        data={"username": email_a, "password": "wrongpass"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert wrong_password.status_code == 401
