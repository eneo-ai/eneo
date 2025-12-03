"""Integration tests covering tenant-scoped LLM credential resolution."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from intric.settings.credential_resolver import CredentialResolver
from intric.tenants.tenant_repo import TenantRepository


@pytest.fixture(autouse=True)
def enable_tenant_credentials(test_settings, monkeypatch):
    """Enable tenant credentials feature for all tests in this module."""
    monkeypatch.setattr(test_settings, "tenant_credentials_enabled", True)


async def _put_tenant_credential(
    client: AsyncClient,
    super_api_key: str,
    tenant_id: str,
    provider: str,
    payload: dict,
) -> None:
    response = await client.put(
        f"/api/v1/sysadmin/tenants/{tenant_id}/credentials/{provider}",
        json=payload,
        headers={"X-API-Key": super_api_key},
    )
    assert response.status_code == 200, response.text


async def _delete_tenant_credential(
    client: AsyncClient,
    super_api_key: str,
    tenant_id: str,
    provider: str,
) -> None:
    response = await client.delete(
        f"/api/v1/sysadmin/tenants/{tenant_id}/credentials/{provider}",
        headers={"X-API-Key": super_api_key},
    )
    assert response.status_code in {200, 404}, response.text


async def _create_tenant(
    client: AsyncClient,
    super_api_key: str,
    name: str,
) -> dict:
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolver_returns_decrypted_tenant_key(
    client: AsyncClient,
    async_session: AsyncSession,
    test_tenant,
    super_admin_token: str,
    encryption_service,
    test_settings,
):
    repo = TenantRepository(async_session)
    tenant = await repo.get(test_tenant.id)

    tenant_key = f"sk-tenant-{uuid4().hex[:12]}"
    await _put_tenant_credential(
        client,
        super_admin_token,
        str(test_tenant.id),
        "openai",
        {"api_key": tenant_key},
    )

    tenant = await repo.get(test_tenant.id)
    resolver = CredentialResolver(
        tenant=tenant,
        settings=test_settings,
        encryption_service=encryption_service,
    )

    resolved = resolver.get_api_key("openai")
    assert resolved == tenant_key


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolver_falls_back_to_global_when_disabled(
    client: AsyncClient,
    async_session: AsyncSession,
    test_tenant,
    super_admin_token: str,
    encryption_service,
    test_settings,
):
    repo = TenantRepository(async_session)
    tenant = await repo.get(test_tenant.id)

    await _delete_tenant_credential(
        client,
        super_admin_token,
        str(test_tenant.id),
        "openai",
    )

    original_flag = test_settings.tenant_credentials_enabled
    original_global_key = test_settings.openai_api_key
    try:
        test_settings.tenant_credentials_enabled = False
        test_settings.openai_api_key = f"sk-global-{uuid4().hex[:8]}"

        resolver = CredentialResolver(
            tenant=tenant,
            settings=test_settings,
            encryption_service=encryption_service,
        )

        resolved = resolver.get_api_key("openai")
        assert resolved == test_settings.openai_api_key
    finally:
        test_settings.tenant_credentials_enabled = original_flag
        test_settings.openai_api_key = original_global_key


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolver_raises_in_strict_mode_without_tenant_key(
    client: AsyncClient,
    async_session: AsyncSession,
    test_tenant,
    super_admin_token: str,
    encryption_service,
    test_settings,
):
    repo = TenantRepository(async_session)
    tenant = await repo.get(test_tenant.id)

    await _delete_tenant_credential(
        client,
        super_admin_token,
        str(test_tenant.id),
        "openai",
    )

    original_flag = test_settings.tenant_credentials_enabled
    try:
        test_settings.tenant_credentials_enabled = True

        resolver = CredentialResolver(
            tenant=tenant,
            settings=test_settings,
            encryption_service=encryption_service,
        )

        with pytest.raises(ValueError) as exc:
            resolver.get_api_key("openai")

        assert "Tenant-specific credentials are enabled" in str(exc.value)
    finally:
        test_settings.tenant_credentials_enabled = original_flag


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolver_isolates_credentials_between_tenants(
    client: AsyncClient,
    async_session: AsyncSession,
    super_admin_token: str,
    encryption_service,
    test_settings,
    mock_transcription_models,
):
    repo = TenantRepository(async_session)

    tenant_a_data = await _create_tenant(client, super_admin_token, f"tenant-a-{uuid4().hex[:6]}")
    tenant_b_data = await _create_tenant(client, super_admin_token, f"tenant-b-{uuid4().hex[:6]}")

    tenant_a_id = UUID(tenant_a_data["id"])
    tenant_b_id = UUID(tenant_b_data["id"])

    key_a = f"sk-tenant-a-{uuid4().hex[:8]}"
    key_b = f"sk-tenant-b-{uuid4().hex[:8]}"

    await _put_tenant_credential(
        client,
        super_admin_token,
        tenant_a_data["id"],
        "openai",
        {"api_key": key_a},
    )
    await _put_tenant_credential(
        client,
        super_admin_token,
        tenant_b_data["id"],
        "openai",
        {"api_key": key_b},
    )

    tenant_a = await repo.get(tenant_a_id)
    tenant_b = await repo.get(tenant_b_id)

    resolver_a = CredentialResolver(
        tenant=tenant_a,
        settings=test_settings,
        encryption_service=encryption_service,
    )
    resolver_b = CredentialResolver(
        tenant=tenant_b,
        settings=test_settings,
        encryption_service=encryption_service,
    )

    assert resolver_a.get_api_key("openai") == key_a
    assert resolver_b.get_api_key("openai") == key_b

    # Ensure resolvers respect strict mode and don't return credentials for other tenants
    with pytest.raises(ValueError):
        CredentialResolver(
            tenant=None,
            settings=test_settings,
            encryption_service=encryption_service,
        ).get_api_key("does-not-exist")
