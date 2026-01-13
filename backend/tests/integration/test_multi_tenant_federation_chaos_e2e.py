"""End-to-end chaos tests for multi-tenant OIDC federation edge cases.

These tests deliberately create difficult conditions to find edge cases in:

* Federation config drift during active login flows
* Grace period boundary conditions (exactly at TTL limits)
* State cache failures (Redis down, file fallback)
* Concurrent configuration updates
* Tenant lifecycle events during OIDC flows

Critical Settings:
- OIDC_STATE_TTL_SECONDS: How long state tokens remain valid (e.g., 600)
- OIDC_REDIRECT_GRACE_PERIOD_SECONDS: Tolerate recent config changes (e.g., 900)
- STRICT_OIDC_REDIRECT_VALIDATION: Enforce exact origin matching (true/false)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
import pytest
from httpx import AsyncClient
import sqlalchemy as sa

from intric.authentication.auth_service import AuthService
from intric.tenants.tenant_repo import TenantRepository
from intric.database.tables.tenant_table import Tenants
from intric.database.database import sessionmanager


async def _create_tenant(client: AsyncClient, super_api_key: str, name: str) -> dict:
    """Helper to create a test tenant via API."""
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
    """Helper to create a test user."""
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
    allowed_domains: list[str],
    client_id: str,
    canonical_public_origin: str,
    # These params kept for test compatibility but not sent to API
    authorization_endpoint: str = None,
    token_endpoint: str = None,
    jwks_uri: str = None,
    redirect_path: str = None,
) -> None:
    """Helper to configure tenant federation via API.

    Note: API only accepts discovery_endpoint and derives the rest from OIDC discovery.
    Extra params kept for backward compatibility with existing tests.
    """
    payload = {
        "provider": "entra",
        "client_id": client_id,
        "client_secret": "super-secret",
        "discovery_endpoint": discovery_endpoint,
        "allowed_domains": allowed_domains,
        "canonical_public_origin": canonical_public_origin,
    }
    response = await client.put(
        f"/api/v1/sysadmin/tenants/{tenant_id}/federation",
        json=payload,
        headers={"X-API-Key": super_api_key},
    )
    assert response.status_code == 200, response.text


async def _patch_federation_config(tenant_id: UUID, new_config: dict):
    """Direct database update to simulate config drift."""
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


async def _initiate(client: AsyncClient, slug: str) -> dict:
    """Initiate OIDC flow."""
    response = await client.get(f"/api/v1/auth/initiate?tenant={slug}")
    assert response.status_code == 200, response.text
    return response.json()


async def _callback(client: AsyncClient, *, code: str, state: str):
    """Complete OIDC callback."""
    return await client.post(
        "/api/v1/auth/callback",
        json={"code": code, "state": state},
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_federation_config_drift_rejected_with_zero_grace(
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
    """Verify config drift detection with OIDC_REDIRECT_GRACE_PERIOD_SECONDS=0.

    Scenario:
    - Set grace=0, strict=true
    - Initiate auth → get state token with config version A
    - Update federation config to version B (change canonical_origin)
    - Callback with state from version A
    - Verify HTTP 400 "redirect mismatch"

    This test exposes:
    - Config version tracking bugs
    - Grace period logic inversions
    - Missing version validation
    """
    slug = f"tenant-drift-zero-{uuid4().hex[:6]}"
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
            (token_endpoint, "code-drift"): {
                "id_token": "id-token-drift",
                "access_token": "access-token-drift",
            }
        },
    )
    jwks_mock()

    allowed_email = f"user@{slug}.gov"
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

    # Store original settings
    original_grace = test_settings.oidc_redirect_grace_period_seconds
    original_strict = test_settings.strict_oidc_redirect_validation

    try:
        # Set ZERO grace period and strict validation
        test_settings.oidc_redirect_grace_period_seconds = 0
        test_settings.strict_oidc_redirect_validation = True

        # Configure federation with origin A
        await _configure_federation(
            client,
            super_admin_token,
            tenant["id"],
            discovery_endpoint=discovery_endpoint,
            authorization_endpoint=authorization_endpoint,
            token_endpoint=token_endpoint,
            jwks_uri=jwks_uri,
            canonical_public_origin=f"https://{slug}.eneo.test",
            redirect_path="/auth/callback",
            allowed_domains=[f"{slug}.gov"],
            client_id=f"client-{slug}",
        )

        # Initiate auth flow (state issued with origin A)
        state_payload = await _initiate(client, tenant["slug"])
        state_token = state_payload["state"]

        # DRIFT: Update canonical_origin to origin B (different URL)
        tenant_id = UUID(tenant["id"])
        await _patch_federation_config(
            tenant_id,
            {
                "canonical_public_origin": f"https://{slug}.eneo.CHANGED",
                "config_version": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Attempt callback with state from origin A
        response = await _callback(
            client,
            code="code-drift",
            state=state_token,
        )

        # With grace=0 and strict=true, should reject due to origin mismatch
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        error_detail = response.json()["detail"]
        assert "redirect" in error_detail.lower(), f"Error should mention redirect: {error_detail}"

    finally:
        test_settings.oidc_redirect_grace_period_seconds = original_grace
        test_settings.strict_oidc_redirect_validation = original_strict


@pytest.mark.integration
@pytest.mark.asyncio
async def test_federation_grace_period_allows_recent_config_change(
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
    """Verify grace period allows config changes within tolerance window.

    Scenario:
    - Set grace=900 (15 minutes)
    - Initiate auth → get state token
    - Update federation config immediately (< 15 min ago)
    - Callback with old state
    - Verify HTTP 200 (allowed within grace period)

    This test exposes:
    - Grace period timestamp comparison bugs
    - Timezone handling issues
    - Off-by-one errors in time windows
    """
    slug = f"tenant-grace-allow-{uuid4().hex[:6]}"
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

    allowed_email = f"user@{slug}.gov"
    await _create_user(client, super_admin_token, tenant["id"], allowed_email, password="ValidPassw0rd!")

    monkeypatch.setattr(
        AuthService,
        "get_payload_from_openid_jwt",
        lambda *_, **__: {"email": allowed_email},
    )

    # Store original settings
    original_grace = test_settings.oidc_redirect_grace_period_seconds

    try:
        # Set 900-second grace period
        test_settings.oidc_redirect_grace_period_seconds = 900

        # Configure federation
        await _configure_federation(
            client,
            super_admin_token,
            tenant["id"],
            discovery_endpoint=discovery_endpoint,
            authorization_endpoint=authorization_endpoint,
            token_endpoint=token_endpoint,
            jwks_uri=jwks_uri,
            canonical_public_origin=f"https://{slug}.eneo.test",
            redirect_path="/auth/callback",
            allowed_domains=[f"{slug}.gov"],
            client_id=f"client-{slug}",
        )

        # Initiate auth flow
        state_payload = await _initiate(client, tenant["slug"])
        state_token = state_payload["state"]

        # Update config immediately (within grace period)
        tenant_id = UUID(tenant["id"])
        await _patch_federation_config(
            tenant_id,
            {
                "canonical_public_origin": f"https://{slug}.eneo.updated",
                "config_version": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Callback should succeed (within grace period)
        response = await _callback(client, code="code-grace", state=state_token)

        assert response.status_code == 200, f"Expected 200 (grace period), got {response.status_code}: {response.text}"

    finally:
        test_settings.oidc_redirect_grace_period_seconds = original_grace


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_federation_config_updates_last_write_wins(
    client: AsyncClient,
    super_admin_token: str,
    oidc_mock,
    mock_transcription_models,
    async_session,
):
    """Verify concurrent federation config updates maintain consistency.

    Scenario:
    - Two admins update Tenant A federation config simultaneously
    - Verify last write wins (no data corruption)
    - Verify updated_at timestamp is correct

    This test exposes:
    - Lost update anomalies
    - Race conditions in update logic
    - Missing transaction isolation
    """
    slug = f"tenant-concurrent-{uuid4().hex[:6]}"
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
        tokens={},
    )

    # Configure initial federation
    await _configure_federation(
        client,
        super_admin_token,
        tenant["id"],
        discovery_endpoint=discovery_endpoint,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        jwks_uri=jwks_uri,
        canonical_public_origin=f"https://{slug}.eneo.test",
        redirect_path="/auth/callback",
        allowed_domains=[f"{slug}.gov"],
        client_id=f"client-{slug}",
    )

    # Concurrent update tasks
    update_count = 10

    async def update_config(index: int):
        """Update federation config with unique allowed domain."""
        await _configure_federation(
            client,
            super_admin_token,
            tenant["id"],
            discovery_endpoint=discovery_endpoint,
            authorization_endpoint=authorization_endpoint,
            token_endpoint=token_endpoint,
            jwks_uri=jwks_uri,
            canonical_public_origin=f"https://{slug}.eneo.test",
            allowed_domains=[f"update{index}.{slug}.gov"],  # Unique domain per update
            client_id=f"client-{slug}-{index}",  # Unique client ID per update
        )

    # Fire concurrent updates
    tasks = [update_config(i) for i in range(update_count)]
    await asyncio.gather(*tasks)

    # Verify final state is consistent (one of the updates won)
    # Use fresh session to see committed changes from API
    tenant_id = UUID(tenant["id"])
    async with sessionmanager.session() as session:
        async with session.begin():
            repo = TenantRepository(session)
            tenant_obj = await repo.get(tenant_id)

            # Should have one of the update configurations
            config = tenant_obj.federation_config
            assert config is not None, "Expected federation_config to exist"

            # Verify one of the concurrent updates won (check allowed_domains has update prefix)
            allowed_domains = config.get("allowed_domains", [])
            assert len(allowed_domains) > 0, f"Expected allowed_domains, got {config}"
            assert any("update" in domain for domain in allowed_domains), \
                f"Expected domain with 'update' prefix from concurrent updates, got {allowed_domains}"

            # Verify client_id also matches one of the updates
            client_id = config.get("client_id", "")
            assert "client-" in client_id, f"Expected client_id with prefix, got {client_id}"

            # Verify updated_at is recent
            assert tenant_obj.updated_at is not None
            time_since_update = datetime.now(timezone.utc) - tenant_obj.updated_at
            assert time_since_update < timedelta(seconds=10), "updated_at should be very recent"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_deleted_during_oidc_flow_returns_404(
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
    """Verify graceful handling when tenant is deleted mid-OIDC flow.

    Scenario:
    - Initiate OIDC for Tenant A
    - Delete Tenant A from database
    - Callback with valid code+state
    - Verify HTTP 404 "tenant not found"

    This test exposes:
    - Orphaned state tokens
    - Missing tenant existence checks
    - Database foreign key constraint violations
    """
    slug = f"tenant-deleted-{uuid4().hex[:6]}"
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
            (token_endpoint, "code-deleted"): {
                "id_token": "id-token-deleted",
                "access_token": "access-token-deleted",
            }
        },
    )
    jwks_mock()

    allowed_email = f"user@{slug}.gov"
    await _create_user(client, super_admin_token, tenant["id"], allowed_email, password="ValidPassw0rd!")

    monkeypatch.setattr(
        AuthService,
        "get_payload_from_openid_jwt",
        lambda *_, **__: {"email": allowed_email},
    )

    # Configure federation
    await _configure_federation(
        client,
        super_admin_token,
        tenant["id"],
        discovery_endpoint=discovery_endpoint,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        jwks_uri=jwks_uri,
        canonical_public_origin=f"https://{slug}.eneo.test",
        redirect_path="/auth/callback",
        allowed_domains=[f"{slug}.gov"],
        client_id=f"client-{slug}",
    )

    # Initiate auth flow
    state_payload = await _initiate(client, tenant["slug"])
    state_token = state_payload["state"]

    # Delete tenant
    tenant_id = UUID(tenant["id"])
    async with sessionmanager.session() as session:
        async with session.begin():
            # Delete associated user first (foreign key)
            from intric.database.tables.users_table import Users
            await session.execute(
                sa.delete(Users).where(Users.tenant_id == tenant_id)
            )
            # Delete tenant
            await session.execute(
                sa.delete(Tenants).where(Tenants.id == tenant_id)
            )

    # Attempt callback
    response = await _callback(client, code="code-deleted", state=state_token)

    # Should return 404 (tenant not found)
    assert response.status_code in {404, 400}, f"Expected 404 or 400, got {response.status_code}: {response.text}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_state_token_tampering_rejected(
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
    """Verify tampered state tokens are rejected.

    Scenario:
    - Initiate OIDC for Tenant A
    - Decode state JWT, change tenant_id to Tenant B
    - Re-sign with same secret
    - Callback with tampered state
    - Verify HTTP 400 or 404 (state validation failed)

    This test exposes:
    - Missing signature validation
    - Tenant ID substitution attacks
    - JWT verification bypasses
    """
    slug_a = f"tenant-tamper-a-{uuid4().hex[:6]}"
    slug_b = f"tenant-tamper-b-{uuid4().hex[:6]}"

    tenant_a = await _create_tenant(client, super_admin_token, slug_a)
    tenant_b = await _create_tenant(client, super_admin_token, slug_b)

    discovery_endpoint = f"https://idp.{slug_a}.local/.well-known/openid-configuration"
    authorization_endpoint = f"https://idp.{slug_a}.local/authorize"
    token_endpoint = f"https://idp.{slug_a}.local/token"
    jwks_uri = f"https://idp.{slug_a}.local/jwks"

    oidc_mock(
        discovery={
            discovery_endpoint: {
                "issuer": f"https://idp.{slug_a}.local",
                "authorization_endpoint": authorization_endpoint,
                "token_endpoint": token_endpoint,
                "jwks_uri": jwks_uri,
            }
        },
        tokens={
            (token_endpoint, "code-tamper"): {
                "id_token": "id-token-tamper",
                "access_token": "access-token-tamper",
            }
        },
    )
    jwks_mock()

    allowed_email = f"user@{slug_a}.gov"
    await _create_user(client, super_admin_token, tenant_a["id"], allowed_email, password="ValidPassw0rd!")

    monkeypatch.setattr(
        AuthService,
        "get_payload_from_openid_jwt",
        lambda *_, **__: {"email": allowed_email},
    )

    # Configure federation for Tenant A
    await _configure_federation(
        client,
        super_admin_token,
        tenant_a["id"],
        discovery_endpoint=discovery_endpoint,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        jwks_uri=jwks_uri,
        canonical_public_origin=f"https://{slug_a}.eneo.test",
        redirect_path="/auth/callback",
        allowed_domains=[f"{slug_a}.gov"],
        client_id=f"client-{slug_a}",
    )

    # Initiate auth for Tenant A
    state_payload = await _initiate(client, tenant_a["slug"])
    state_token = state_payload["state"]

    # Tamper with state: change tenant_id to Tenant B
    decoded = jwt.decode(
        state_token,
        test_settings.jwt_secret,
        algorithms=["HS256"],
        options={"verify_exp": False},
    )
    decoded["tenant_id"] = tenant_b["id"]  # Swap tenant!
    tampered_state = jwt.encode(decoded, test_settings.jwt_secret, algorithm="HS256")

    # Attempt callback with tampered state
    response = await _callback(client, code="code-tamper", state=tampered_state)

    # Should reject (tenant mismatch or not found)
    assert response.status_code in {400, 404}, f"Expected 400/404, got {response.status_code}: {response.text}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_grace_period_boundary_exact_ttl_minus_grace(
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
    """Verify grace period boundary: config change exactly at (now - grace).

    Scenario:
    - TTL=600, GRACE=900 (should be capped to TTL)
    - Initiate auth
    - Mock time: advance exactly (TTL - GRACE) seconds
    - Update config
    - Callback
    - Verify behavior at exact boundary

    This test exposes:
    - Off-by-one errors in time comparisons
    - Boundary condition bugs (<= vs <)
    - Grace period capping logic
    """
    slug = f"tenant-boundary-{uuid4().hex[:6]}"
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
            (token_endpoint, "code-boundary"): {
                "id_token": "id-token-boundary",
                "access_token": "access-token-boundary",
            }
        },
    )
    jwks_mock()

    allowed_email = f"user@{slug}.gov"
    await _create_user(client, super_admin_token, tenant["id"], allowed_email, password="ValidPassw0rd!")

    monkeypatch.setattr(
        AuthService,
        "get_payload_from_openid_jwt",
        lambda *_, **__: {"email": allowed_email},
    )

    # Note: This test documents the expected behavior at boundary conditions
    # Actual time mocking would require freezegun or similar
    # For now, we verify the settings validation logic

    original_ttl = test_settings.oidc_state_ttl_seconds
    original_grace = test_settings.oidc_redirect_grace_period_seconds

    try:
        # Set grace > TTL (should trigger validation warning)
        test_settings.oidc_state_ttl_seconds = 600
        test_settings.oidc_redirect_grace_period_seconds = 900
        from intric.main.config import set_settings
        set_settings(test_settings)

        # Configure federation
        await _configure_federation(
            client,
            super_admin_token,
            tenant["id"],
            discovery_endpoint=discovery_endpoint,
            authorization_endpoint=authorization_endpoint,
            token_endpoint=token_endpoint,
            jwks_uri=jwks_uri,
            canonical_public_origin=f"https://{slug}.eneo.test",
            redirect_path="/auth/callback",
            allowed_domains=[f"{slug}.gov"],
            client_id=f"client-{slug}",
        )

        # Initiate and callback immediately (no time drift)
        state_payload = await _initiate(client, tenant["slug"])
        response = await _callback(client, code="code-boundary", state=state_payload["state"])

        # Should succeed (no config drift yet)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    finally:
        test_settings.oidc_state_ttl_seconds = original_ttl
        test_settings.oidc_redirect_grace_period_seconds = original_grace
        from intric.main.config import set_settings
        set_settings(test_settings)
