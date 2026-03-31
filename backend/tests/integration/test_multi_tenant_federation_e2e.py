"""Integration tests for multi-tenant OIDC federation flows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
import pytest
from httpx import AsyncClient
import sqlalchemy as sa

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from intric.authentication.auth_service import AuthService
from intric.tenants.tenant_repo import TenantRepository
from intric.database.tables.tenant_table import Tenants
from intric.database.database import sessionmanager


async def _patch_federation_config(async_session, tenant_id: UUID, new_config: dict):
    """Patch federation config using its own session to avoid transaction conflicts."""
    async with sessionmanager.session() as session:
        async with session.begin():
            result = await session.execute(
                sa.select(Tenants.__table__.c.federation_config).where(Tenants.__table__.c.id == tenant_id)
            )
            current = dict(result.scalar_one())
            config = {**current, **new_config}
            await session.execute(
                sa.update(Tenants.__table__)
                .where(Tenants.__table__.c.id == tenant_id)
                .values(federation_config=config, updated_at=datetime.now(timezone.utc))
            )


async def _create_tenant(client: AsyncClient, super_api_key: str, name: str) -> dict:
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


async def _create_user(
    client: AsyncClient,
    super_api_key: str,
    tenant_id: str,
    email: str,
    password: str,
) -> dict:
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
    client: AsyncClient,
    super_api_key: str,
    tenant_id: str,
    *,
    discovery_endpoint: str,
    authorization_endpoint: str,
    token_endpoint: str,
    jwks_uri: str,
    canonical_origin: str,
    redirect_path: str,
    allowed_domains: list[str],
    client_id: str,
) -> None:
    payload = {
        "provider": "entra",
        "client_id": client_id,
        "client_secret": "super-secret",
        "discovery_endpoint": discovery_endpoint,
        "authorization_endpoint": authorization_endpoint,
        "token_endpoint": token_endpoint,
        "jwks_uri": jwks_uri,
        "canonical_public_origin": canonical_origin,
        "redirect_path": redirect_path,
        "allowed_domains": allowed_domains,
    }
    response = await client.put(
        f"/api/v1/sysadmin/tenants/{tenant_id}/federation",
        json=payload,
        headers={"X-API-Key": super_api_key},
    )
    assert response.status_code == 200, response.text


async def _initiate(client: AsyncClient, slug: str) -> dict:
    response = await client.get(f"/api/v1/auth/initiate?tenant={slug}")
    assert response.status_code == 200, response.text
    return response.json()


async def _callback(client: AsyncClient, *, code: str, state: str):
    return await client.post(
        "/api/v1/auth/callback",
        json={"code": code, "state": state},
    )


def _generate_rs256_keypair() -> tuple[str, str]:
    """Generate an RSA keypair for RS256 signing within tests."""

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    return private_pem, public_pem


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_federation_updates_single_field_without_full_payload(
    client: AsyncClient,
    async_session,
    super_admin_token: str,
    oidc_mock,
    mock_transcription_models,
):
    slug = f"federation-patch-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, slug)
    tenant_id = UUID(tenant["id"])

    discovery_endpoint = f"https://idp.{slug}.local/.well-known/openid-configuration"
    oidc_mock(
        discovery={
            discovery_endpoint: {
                "issuer": f"https://idp.{slug}.local",
                "authorization_endpoint": f"https://idp.{slug}.local/authorize",
                "token_endpoint": f"https://idp.{slug}.local/token",
                "jwks_uri": f"https://idp.{slug}.local/jwks",
            }
        },
        tokens={},
    )

    await _configure_federation(
        client,
        super_admin_token,
        tenant["id"],
        discovery_endpoint=discovery_endpoint,
        authorization_endpoint=f"https://idp.{slug}.local/authorize",
        token_endpoint=f"https://idp.{slug}.local/token",
        jwks_uri=f"https://idp.{slug}.local/jwks",
        canonical_origin=f"https://{slug}.eneo.test",
        redirect_path="/auth/callback",
        allowed_domains=[f"{slug}.example.com"],
        client_id=f"client-{slug}",
    )

    response = await client.patch(
        f"/api/v1/sysadmin/tenants/{tenant['id']}/federation",
        json={"allowed_domains": [f"{slug}.example.com", "new.example.com"]},
        headers={"X-API-Key": super_admin_token},
    )
    assert response.status_code == 200, response.text
    assert response.json()["message"] == "Federation config for entra updated successfully"

    repo = TenantRepository(async_session)
    stored = (await repo.get(tenant_id)).federation_config
    assert stored["allowed_domains"] == [f"{slug}.example.com", "new.example.com"]
    assert stored["client_id"] == f"client-{slug}"
    assert stored["discovery_endpoint"] == discovery_endpoint
    assert stored["canonical_public_origin"] == f"https://{slug}.eneo.test"
    assert stored["redirect_path"] == "/auth/callback"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_federation_updates_client_secret_only(
    client: AsyncClient,
    async_session,
    super_admin_token: str,
    oidc_mock,
    encryption_service,
    mock_transcription_models,
):
    slug = f"federation-secret-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, slug)
    tenant_id = UUID(tenant["id"])

    discovery_endpoint = f"https://idp.{slug}.local/.well-known/openid-configuration"
    oidc_mock(
        discovery={
            discovery_endpoint: {
                "issuer": f"https://idp.{slug}.local",
                "authorization_endpoint": f"https://idp.{slug}.local/authorize",
                "token_endpoint": f"https://idp.{slug}.local/token",
                "jwks_uri": f"https://idp.{slug}.local/jwks",
            }
        },
        tokens={},
    )

    await _configure_federation(
        client,
        super_admin_token,
        tenant["id"],
        discovery_endpoint=discovery_endpoint,
        authorization_endpoint=f"https://idp.{slug}.local/authorize",
        token_endpoint=f"https://idp.{slug}.local/token",
        jwks_uri=f"https://idp.{slug}.local/jwks",
        canonical_origin=f"https://{slug}.eneo.test",
        redirect_path="/auth/callback",
        allowed_domains=[f"{slug}.example.com"],
        client_id=f"client-{slug}",
    )

    repo = TenantRepository(async_session)
    before = (await repo.get(tenant_id)).federation_config

    new_secret = f"rotated-secret-{uuid4().hex[:8]}"
    response = await client.patch(
        f"/api/v1/sysadmin/tenants/{tenant['id']}/federation",
        json={"client_secret": new_secret},
        headers={"X-API-Key": super_admin_token},
    )
    assert response.status_code == 200, response.text
    assert response.json()["masked_secret"].endswith(new_secret[-4:])

    after = (await repo.get(tenant_id)).federation_config
    assert after["client_id"] == before["client_id"]
    assert after["discovery_endpoint"] == before["discovery_endpoint"]
    assert after["client_secret"] != before["client_secret"]
    assert encryption_service.decrypt(after["client_secret"]) == new_secret


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_federation_refreshes_discovery_fields(
    client: AsyncClient,
    async_session,
    super_admin_token: str,
    oidc_mock,
    mock_transcription_models,
):
    slug = f"federation-discovery-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, slug)
    tenant_id = UUID(tenant["id"])

    first_discovery = f"https://idp.{slug}.local/.well-known/openid-configuration"
    second_discovery = f"https://idp2.{slug}.local/.well-known/openid-configuration"
    oidc_mock(
        discovery={
            first_discovery: {
                "issuer": f"https://idp.{slug}.local",
                "authorization_endpoint": f"https://idp.{slug}.local/authorize",
                "token_endpoint": f"https://idp.{slug}.local/token",
                "jwks_uri": f"https://idp.{slug}.local/jwks",
            },
            second_discovery: {
                "issuer": f"https://idp2.{slug}.local",
                "authorization_endpoint": f"https://idp2.{slug}.local/authorize",
                "token_endpoint": f"https://idp2.{slug}.local/token",
                "jwks_uri": f"https://idp2.{slug}.local/jwks",
                "token_endpoint_auth_methods_supported": ["client_secret_basic"],
            },
        },
        tokens={},
    )

    await _configure_federation(
        client,
        super_admin_token,
        tenant["id"],
        discovery_endpoint=first_discovery,
        authorization_endpoint=f"https://idp.{slug}.local/authorize",
        token_endpoint=f"https://idp.{slug}.local/token",
        jwks_uri=f"https://idp.{slug}.local/jwks",
        canonical_origin=f"https://{slug}.eneo.test",
        redirect_path="/auth/callback",
        allowed_domains=[f"{slug}.example.com"],
        client_id=f"client-{slug}",
    )

    response = await client.patch(
        f"/api/v1/sysadmin/tenants/{tenant['id']}/federation",
        json={"discovery_endpoint": second_discovery},
        headers={"X-API-Key": super_admin_token},
    )
    assert response.status_code == 200, response.text

    repo = TenantRepository(async_session)
    stored = (await repo.get(tenant_id)).federation_config
    assert stored["discovery_endpoint"] == second_discovery
    assert stored["issuer"] == f"https://idp2.{slug}.local"
    assert stored["authorization_endpoint"] == f"https://idp2.{slug}.local/authorize"
    assert stored["token_endpoint"] == f"https://idp2.{slug}.local/token"
    assert stored["jwks_uri"] == f"https://idp2.{slug}.local/jwks"
    assert stored["token_endpoint_auth_method"] == "client_secret_basic"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_federation_clears_optional_fields(
    client: AsyncClient,
    async_session,
    super_admin_token: str,
    oidc_mock,
    mock_transcription_models,
):
    slug = f"federation-clear-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, slug)
    tenant_id = UUID(tenant["id"])

    discovery_endpoint = f"https://idp.{slug}.local/.well-known/openid-configuration"
    oidc_mock(
        discovery={
            discovery_endpoint: {
                "issuer": f"https://idp.{slug}.local",
                "authorization_endpoint": f"https://idp.{slug}.local/authorize",
                "token_endpoint": f"https://idp.{slug}.local/token",
                "jwks_uri": f"https://idp.{slug}.local/jwks",
            }
        },
        tokens={},
    )

    initial_response = await client.put(
        f"/api/v1/sysadmin/tenants/{tenant['id']}/federation",
        json={
            "provider": "entra",
            "client_id": f"client-{slug}",
            "client_secret": "super-secret",
            "discovery_endpoint": discovery_endpoint,
            "canonical_public_origin": f"https://{slug}.eneo.test",
            "redirect_path": "/auth/callback",
            "additional_redirect_uris": [f"https://extra.{slug}.eneo.test/auth/callback"],
            "allowed_domains": [f"{slug}.example.com"],
        },
        headers={"X-API-Key": super_admin_token},
    )
    assert initial_response.status_code == 200, initial_response.text

    response = await client.patch(
        f"/api/v1/sysadmin/tenants/{tenant['id']}/federation",
        json={
            "canonical_public_origin": None,
            "redirect_path": None,
            "additional_redirect_uris": [],
        },
        headers={"X-API-Key": super_admin_token},
    )
    assert response.status_code == 200, response.text

    repo = TenantRepository(async_session)
    stored = (await repo.get(tenant_id)).federation_config
    assert "canonical_public_origin" not in stored
    assert "redirect_path" not in stored
    assert stored["additional_redirect_uris"] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_federation_requires_existing_config(
    client: AsyncClient,
    super_admin_token: str,
    mock_transcription_models,
):
    slug = f"federation-missing-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, slug)

    response = await client.patch(
        f"/api/v1/sysadmin/tenants/{tenant['id']}/federation",
        json={"allowed_domains": ["missing.example.com"]},
        headers={"X-API-Key": super_admin_token},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "No federation config found for tenant"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_put_federation_still_requires_full_payload(
    client: AsyncClient,
    super_admin_token: str,
    mock_transcription_models,
):
    slug = f"federation-put-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, slug)

    response = await client.put(
        f"/api/v1/sysadmin/tenants/{tenant['id']}/federation",
        json={"allowed_domains": ["incomplete.example.com"]},
        headers={"X-API-Key": super_admin_token},
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_federation_initiate_requires_valid_tenant(
    client: AsyncClient,
    super_admin_token: str,
    oidc_mock,
    mock_transcription_models,
):
    slug = f"federation-init-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, slug)

    # Set up mock BEFORE configuring federation (config validates discovery endpoint)
    discovery_endpoint = f"https://idp.{slug}.local/.well-known/openid-configuration"
    oidc_mock(
        discovery={
            discovery_endpoint: {
                "issuer": f"https://idp.{slug}.local",
                "authorization_endpoint": f"https://idp.{slug}.local/authorize",
                "token_endpoint": f"https://idp.{slug}.local/token",
                "jwks_uri": f"https://idp.{slug}.local/jwks",
            }
        },
        tokens={},
    )

    await _configure_federation(
        client,
        super_admin_token,
        tenant["id"],
        discovery_endpoint=discovery_endpoint,
        authorization_endpoint=f"https://idp.{slug}.local/authorize",
        token_endpoint=f"https://idp.{slug}.local/token",
        jwks_uri=f"https://idp.{slug}.local/jwks",
        canonical_origin=f"https://{slug}.eneo.test",
        redirect_path="/auth/callback",
        allowed_domains=[f"{slug}.example.com"],
        client_id=f"client-{slug}",
    )

    response = await client.get(f"/api/v1/auth/initiate?tenant={tenant['slug']}")
    assert response.status_code == 200
    data = response.json()
    assert data["authorization_url"].startswith(f"https://idp.{slug}.local/authorize")
    assert data["state"]

    missing_slug = await client.get("/api/v1/auth/initiate")
    assert missing_slug.status_code == 400

    unknown_tenant = await client.get("/api/v1/auth/initiate?tenant=does-not-exist")
    assert unknown_tenant.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_federation_callback_enforces_allowed_domains(
    client: AsyncClient,
    super_admin_token: str,
    patch_auth_service_jwt,
    oidc_mock,
    jwks_mock,
    monkeypatch,
    mock_transcription_models,
):
    slug = f"federation-domain-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, slug)

    discovery_endpoint = f"https://idp.{slug}.local/.well-known/openid-configuration"
    authorization_endpoint = f"https://idp.{slug}.local/authorize"
    token_endpoint = f"https://idp.{slug}.local/token"
    jwks_uri = f"https://idp.{slug}.local/jwks"

    # Set up mock BEFORE configuring federation
    oidc_mock(
        discovery={
            discovery_endpoint: {
                "issuer": f"https://idp.{slug}.local",
                "authorization_endpoint": authorization_endpoint,
                "token_endpoint": token_endpoint,
                "jwks_uri": jwks_uri,
            }
        },
        tokens={
            (token_endpoint, "code-allowed"): {
                "id_token": "id-token-allowed",
                "access_token": "access-token-allowed",
            },
            (token_endpoint, "code-blocked"): {
                "id_token": "id-token-blocked",
                "access_token": "access-token-blocked",
            },
        },
    )
    jwks_mock()

    await _configure_federation(
        client,
        super_admin_token,
        tenant["id"],
        discovery_endpoint=discovery_endpoint,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        jwks_uri=jwks_uri,
        canonical_origin=f"https://{slug}.eneo.test",
        redirect_path="/auth/callback",
        allowed_domains=[f"{slug}.gov"],
        client_id=f"client-{slug}",
    )

    allowed_email = f"alice@{slug}.gov"
    await _create_user(
        client,
        super_admin_token,
        tenant["id"],
        allowed_email,
        password="ValidPassw0rd!",
    )

    token_email_map = {
        "id-token-allowed": allowed_email,
        "id-token-blocked": f"intruder@other-{slug}.com",
    }

    def _fake_payload(
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
        return {"email": token_email_map[id_token]}

    monkeypatch.setattr(AuthService, "get_payload_from_openid_jwt", _fake_payload)

    state_payload = await _initiate(client, tenant["slug"])
    success = await _callback(client, code="code-allowed", state=state_payload["state"])
    assert success.status_code == 200, success.text

    second_state = await _initiate(client, tenant["slug"])
    failure = await _callback(client, code="code-blocked", state=second_state["state"])
    assert failure.status_code == 403
    assert "not allowed" in failure.json()["detail"].lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_federation_callback_rejects_tampered_state(
    client: AsyncClient,
    super_admin_token: str,
    patch_auth_service_jwt,
    oidc_mock,
    jwks_mock,
    monkeypatch,
    mock_transcription_models,
    test_settings,
):
    slug = f"federation-state-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, slug)

    discovery_endpoint = f"https://idp.{slug}.local/.well-known/openid-configuration"
    authorization_endpoint = f"https://idp.{slug}.local/authorize"
    token_endpoint = f"https://idp.{slug}.local/token"
    jwks_uri = f"https://idp.{slug}.local/jwks"

    # Set up mock BEFORE configuring federation
    oidc_mock(
        discovery={
            discovery_endpoint: {
                "issuer": f"https://idp.{slug}.local",
                "authorization_endpoint": authorization_endpoint,
                "token_endpoint": token_endpoint,
                "jwks_uri": jwks_uri,
            }
        },
        tokens={
            (token_endpoint, "code-legit"): {
                "id_token": "id-token-legit",
                "access_token": "access-token-legit",
            }
        },
    )
    jwks_mock()

    await _configure_federation(
        client,
        super_admin_token,
        tenant["id"],
        discovery_endpoint=discovery_endpoint,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        jwks_uri=jwks_uri,
        canonical_origin=f"https://{slug}.eneo.test",
        redirect_path="/auth/callback",
        allowed_domains=[f"{slug}.gov"],
        client_id=f"client-{slug}",
    )

    await _create_user(
        client,
        super_admin_token,
        tenant["id"],
        f"user@{slug}.gov",
        password="ValidPassw0rd!",
    )

    monkeypatch.setattr(
        AuthService,
        "get_payload_from_openid_jwt",
        lambda *_, **__: {"email": f"user@{slug}.gov"},
    )

    state_payload = await _initiate(client, tenant["slug"])
    state_token = state_payload["state"]

    decoded = jwt.decode(
        state_token,
        test_settings.jwt_secret,
        algorithms=["HS256"],
        options={"verify_exp": False},
    )
    decoded["tenant_id"] = str(uuid4())
    tampered_state = jwt.encode(decoded, test_settings.jwt_secret, algorithm="HS256")

    tampered = await _callback(client, code="code-legit", state=tampered_state)
    assert tampered.status_code in {400, 404}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_federation_callback_accepts_future_iat_within_leeway(
    client: AsyncClient,
    super_admin_token: str,
    patch_auth_service_jwt,
    oidc_mock,
    jwks_mock,
    mock_transcription_models,
):
    slug = f"federation-iat-leeway-ok-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, slug)

    discovery_endpoint = f"https://idp.{slug}.local/.well-known/openid-configuration"
    authorization_endpoint = f"https://idp.{slug}.local/authorize"
    token_endpoint = f"https://idp.{slug}.local/token"
    jwks_uri = f"https://idp.{slug}.local/jwks"
    issuer = f"https://idp.{slug}.local"
    client_id = f"client-{slug}"

    private_key, public_key = _generate_rs256_keypair()
    jwks_mock(default_key=public_key)

    allowed_email = f"owner@{slug}.gov"

    now = datetime.now(timezone.utc)

    def _build_future_token(skew_seconds: int) -> str:
        payload = {
            "iss": issuer,
            "aud": client_id,
            "sub": f"user-{slug}",
            "email": allowed_email,
            "iat": int((now + timedelta(seconds=skew_seconds)).timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        }
        return jwt.encode(payload, private_key, algorithm="RS256")

    within_leeway_token = _build_future_token(skew_seconds=90)

    oidc_mock(
        discovery={
            discovery_endpoint: {
                "issuer": issuer,
                "authorization_endpoint": authorization_endpoint,
                "token_endpoint": token_endpoint,
                "jwks_uri": jwks_uri,
            }
        },
        tokens={
            (token_endpoint, "code-leeway-ok"): {
                "id_token": within_leeway_token,
                "access_token": "access-token-leeway-ok",
            }
        },
    )

    await _configure_federation(
        client,
        super_admin_token,
        tenant["id"],
        discovery_endpoint=discovery_endpoint,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        jwks_uri=jwks_uri,
        canonical_origin=f"https://{slug}.eneo.test",
        redirect_path="/auth/callback",
        allowed_domains=[f"{slug}.gov"],
        client_id=client_id,
    )

    await _create_user(
        client,
        super_admin_token,
        tenant["id"],
        allowed_email,
        password="ValidPassw0rd!",
    )

    state_payload = await _initiate(client, tenant["slug"])
    response = await _callback(
        client,
        code="code-leeway-ok",
        state=state_payload["state"],
    )

    assert response.status_code == 200, response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_federation_callback_rejects_future_iat_beyond_leeway(
    client: AsyncClient,
    super_admin_token: str,
    patch_auth_service_jwt,
    oidc_mock,
    jwks_mock,
    mock_transcription_models,
):
    slug = f"federation-iat-leeway-fail-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, slug)

    discovery_endpoint = f"https://idp.{slug}.local/.well-known/openid-configuration"
    authorization_endpoint = f"https://idp.{slug}.local/authorize"
    token_endpoint = f"https://idp.{slug}.local/token"
    jwks_uri = f"https://idp.{slug}.local/jwks"
    issuer = f"https://idp.{slug}.local"
    client_id = f"client-{slug}"

    private_key, public_key = _generate_rs256_keypair()
    jwks_mock(default_key=public_key)

    allowed_email = f"owner@{slug}.gov"

    now = datetime.now(timezone.utc)

    def _build_future_token(skew_seconds: int) -> str:
        payload = {
            "iss": issuer,
            "aud": client_id,
            "sub": f"user-{slug}",
            "email": allowed_email,
            "iat": int((now + timedelta(seconds=skew_seconds)).timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        }
        return jwt.encode(payload, private_key, algorithm="RS256")

    beyond_leeway_token = _build_future_token(skew_seconds=300)

    oidc_mock(
        discovery={
            discovery_endpoint: {
                "issuer": issuer,
                "authorization_endpoint": authorization_endpoint,
                "token_endpoint": token_endpoint,
                "jwks_uri": jwks_uri,
            }
        },
        tokens={
            (token_endpoint, "code-leeway-fail"): {
                "id_token": beyond_leeway_token,
                "access_token": "access-token-leeway-fail",
            }
        },
    )

    await _configure_federation(
        client,
        super_admin_token,
        tenant["id"],
        discovery_endpoint=discovery_endpoint,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        jwks_uri=jwks_uri,
        canonical_origin=f"https://{slug}.eneo.test",
        redirect_path="/auth/callback",
        allowed_domains=[f"{slug}.gov"],
        client_id=client_id,
    )

    await _create_user(
        client,
        super_admin_token,
        tenant["id"],
        allowed_email,
        password="ValidPassw0rd!",
    )

    state_payload = await _initiate(client, tenant["slug"])
    response = await _callback(
        client,
        code="code-leeway-fail",
        state=state_payload["state"],
    )

    assert response.status_code == 500, response.text
    detail = response.json().get("detail", "")
    assert "unexpected" in detail.lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_federation_callback_rejects_redirect_mismatch_without_grace(
    client: AsyncClient,
    super_admin_token: str,
    patch_auth_service_jwt,
    oidc_mock,
    jwks_mock,
    monkeypatch,
    mock_transcription_models,
    test_settings,
    async_session,
):
    slug = f"federation-redirect-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, slug)

    discovery_endpoint = f"https://idp.{slug}.local/.well-known/openid-configuration"
    authorization_endpoint = f"https://idp.{slug}.local/authorize"
    token_endpoint = f"https://idp.{slug}.local/token"
    jwks_uri = f"https://idp.{slug}.local/jwks"

    oidc_mock(
        discovery={
            discovery_endpoint: {
                "issuer": f"https://idp.{slug}.local",
                "authorization_endpoint": authorization_endpoint,
                "token_endpoint": token_endpoint,
                "jwks_uri": jwks_uri,
            }
        },
        tokens={
            (token_endpoint, "code-old-config"): {
                "id_token": "id-token-redirect-test",
                "access_token": "access-token-redirect-test",
            }
        },
    )
    jwks_mock()

    allowed_email = f"admin@{slug}.gov"
    await _create_user(
        client,
        super_admin_token,
        tenant["id"],
        allowed_email,
        password="ValidPassw0rd!",
    )

    monkeypatch.setattr(
        AuthService,
        "get_payload_from_openid_jwt",
        lambda *_, **__: {"email": allowed_email},
    )

    original_grace = test_settings.oidc_redirect_grace_period_seconds
    original_strict = test_settings.strict_oidc_redirect_validation
    try:
        test_settings.oidc_redirect_grace_period_seconds = 0
        test_settings.strict_oidc_redirect_validation = True

        await _configure_federation(
            client,
            super_admin_token,
            tenant["id"],
            discovery_endpoint=discovery_endpoint,
            authorization_endpoint=authorization_endpoint,
            token_endpoint=token_endpoint,
            jwks_uri=jwks_uri,
            canonical_origin=f"https://{slug}.eneo.test",
            redirect_path="/auth/callback",
            allowed_domains=[f"{slug}.gov"],
            client_id=f"client-{slug}",
        )

        tenant_id = UUID(tenant["id"])
        repo = TenantRepository(async_session)
        tenant_model = await repo.get(tenant_id)
        base_config = dict(tenant_model.federation_config)
        base_config.setdefault("redirect_path", "/auth/callback")
        base_config.setdefault("issuer", base_config.get("issuer", f"https://idp.{slug}.local"))
        base_config.setdefault("authorization_endpoint", authorization_endpoint)
        base_config.setdefault("token_endpoint", token_endpoint)
        base_config.setdefault("jwks_uri", jwks_uri)
        base_config.setdefault("client_id", base_config.get("client_id", f"client-{slug}"))
        base_config.setdefault("client_secret", base_config.get("client_secret", "super-secret"))
        base_config.setdefault("provider", base_config.get("provider", "entra"))
        base_config.setdefault("discovery_endpoint", discovery_endpoint)
        base_config.setdefault("allowed_domains", base_config.get("allowed_domains", [f"{slug}.gov"]))
        base_config.setdefault("scopes", base_config.get("scopes", ["openid", "email", "profile"]))

        initial_config = base_config.copy()
        initial_config.update(
            {
                "canonical_public_origin": f"https://{slug}.eneo.test",
                "redirect_path": "/auth/callback",
                "config_version": datetime.now(timezone.utc).isoformat(),
            }
        )

        await _patch_federation_config(async_session, tenant_id, initial_config)

        state_payload = await _initiate(client, tenant["slug"])

        # Update canonical origin after the state was issued to simulate config drift
        updated_config = initial_config.copy()
        updated_config.update(
            {
                "canonical_public_origin": f"https://{slug}.eneo.updated",
                "redirect_path": "/auth/callback",
                "config_version": datetime.now(timezone.utc).isoformat(),
            }
        )
        await _patch_federation_config(async_session, tenant_id, updated_config)

        response = await _callback(
            client,
            code="code-old-config",
            state=state_payload["state"],
        )

        assert response.status_code == 400
        assert "redirect" in response.json()["detail"].lower()
    finally:
        test_settings.oidc_redirect_grace_period_seconds = original_grace
        test_settings.strict_oidc_redirect_validation = original_strict


@pytest.mark.integration
@pytest.mark.asyncio
async def test_federation_callback_allows_recent_config_change_within_grace(
    client: AsyncClient,
    super_admin_token: str,
    patch_auth_service_jwt,
    oidc_mock,
    jwks_mock,
    monkeypatch,
    mock_transcription_models,
    test_settings,
    async_session,
):
    slug = f"federation-redirect-grace-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, slug)

    discovery_endpoint = f"https://idp.{slug}.local/.well-known/openid-configuration"
    authorization_endpoint = f"https://idp.{slug}.local/authorize"
    token_endpoint = f"https://idp.{slug}.local/token"
    jwks_uri = f"https://idp.{slug}.local/jwks"

    oidc_mock(
        discovery={
            discovery_endpoint: {
                "issuer": f"https://idp.{slug}.local",
                "authorization_endpoint": authorization_endpoint,
                "token_endpoint": token_endpoint,
                "jwks_uri": jwks_uri,
            }
        },
        tokens={
            (token_endpoint, "code-grace"): {
                "id_token": "id-token-grace",
                "access_token": "access-token-grace",
            }
        },
    )
    jwks_mock()

    allowed_email = f"owner@{slug}.gov"
    await _create_user(
        client,
        super_admin_token,
        tenant["id"],
        allowed_email,
        password="ValidPassw0rd!",
    )

    monkeypatch.setattr(
        AuthService,
        "get_payload_from_openid_jwt",
        lambda *_, **__: {"email": allowed_email},
    )

    # Configure federation first to ensure all required fields are present
    await _configure_federation(
        client,
        super_admin_token,
        tenant["id"],
        discovery_endpoint=discovery_endpoint,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        jwks_uri=jwks_uri,
        canonical_origin=f"https://{slug}.eneo.test",
        redirect_path="/auth/callback",
        allowed_domains=[f"{slug}.gov"],
        client_id=f"client-{slug}",
    )

    tenant_id = UUID(tenant["id"])
    initial_config = {
        "canonical_public_origin": f"https://{slug}.eneo.test",
        "redirect_path": "/auth/callback",
        "config_version": datetime.now(timezone.utc).isoformat(),
    }
    await _patch_federation_config(async_session, tenant_id, initial_config)

    state_payload = await _initiate(client, tenant["slug"])

    drift_config = initial_config.copy()
    drift_config.update(
        {
            "canonical_public_origin": f"https://{slug}.eneo.new",
            "redirect_path": "/auth/callback",
            "config_version": datetime.now(timezone.utc).isoformat(),
        }
    )
    await _patch_federation_config(async_session, tenant_id, drift_config)

    response = await _callback(
        client,
        code="code-grace",
        state=state_payload["state"],
    )

    assert response.status_code == 200
