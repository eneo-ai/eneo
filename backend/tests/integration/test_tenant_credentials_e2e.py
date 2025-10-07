"""
Integration tests for tenant-specific API credentials (TDD - Tests fail first).

Tests cover all 5 user stories from quickstart.md:
- Story 1: Municipality admin sets OpenAI API key
- Story 2: Azure OpenAI with data residency requirements
- Story 3: Multi-provider configuration
- Story 4: Backward compatibility with global credentials
- Edge Case: Strict error handling without fallback

These tests MUST FAIL initially since:
- Admin API endpoints (/admin/tenants/{id}/credentials/*) don't exist
- TenantRepo.get_by_id() needs implementation
- CredentialResolver doesn't exist yet
- Tenant.api_credentials field not in database schema
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.integration
@pytest.mark.asyncio
async def test_municipality_admin_sets_api_key(
    client: AsyncClient,
    async_session: AsyncSession,
    test_tenant,
    super_admin_token: str,
):
    """
    Story 1: Municipality admin sets OpenAI API key.

    Scenario:
    - Admin sets tenant-specific OpenAI key
    - Key is encrypted and stored in database
    - Masked key returned in response
    - Full key retrievable via repository

    Expected to FAIL: Admin endpoints not implemented yet.
    """
    tenant_id = test_tenant.id
    test_key = "sk-tenant-test-key-abc123"

    # Step 1: Set credential via admin API
    response = await client.put(
        f"/admin/tenants/{tenant_id}/credentials/openai",
        json={"api_key": test_key},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    data = response.json()
    assert data["provider"] == "openai"
    assert data["masked_key"] == "sk-...c123", "Key should be masked showing last 4 chars"
    assert "api_key" not in data, "Full key should never be returned in API response"
    assert data["set_at"] is not None, "Timestamp should be recorded"

    # Step 2: Verify stored in database with encryption
    from intric.tenants.tenant_repo import TenantRepo

    repo = TenantRepo(async_session)
    tenant = await repo.get_by_id(tenant_id)

    assert tenant is not None, "Tenant should exist"
    assert hasattr(tenant, "api_credentials"), "Tenant should have api_credentials field"
    assert "openai" in tenant.api_credentials, "OpenAI credentials should be stored"

    openai_cred = tenant.api_credentials["openai"]
    assert openai_cred["api_key"] == test_key, "Full key should be stored (encrypted)"
    assert "set_at" in openai_cred, "Timestamp should be stored"

    # Step 3: List credentials shows masked key
    response = await client.get(
        f"/admin/tenants/{tenant_id}/credentials",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 200

    data = response.json()
    assert "credentials" in data
    creds = data["credentials"]
    assert len(creds) == 1, "Should have exactly one credential"

    openai_cred = next((c for c in creds if c["provider"] == "openai"), None)
    assert openai_cred is not None, "OpenAI credential should be in list"
    assert openai_cred["masked_key"] == "sk-...c123"
    assert "api_key" not in openai_cred, "Full key should never be exposed"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_azure_with_data_residency(
    client: AsyncClient,
    async_session: AsyncSession,
    test_tenant,
    super_admin_token: str,
):
    """
    Story 2: Azure OpenAI with Swedish data residency requirements.

    Scenario:
    - Municipality needs data to stay in Sweden
    - Sets Azure OpenAI with Swedish endpoint
    - All required Azure config stored (endpoint, version, deployment)
    - Masked key returned without exposing full credential

    Expected to FAIL: Azure credential endpoint not implemented.
    """
    tenant_id = test_tenant.id

    # Set Azure credential with all required fields
    azure_config = {
        "api_key": "azure-key-sweden-456def",
        "endpoint": "https://sweden.openai.azure.com/",
        "api_version": "2024-02-15-preview",
        "deployment_name": "gpt-4-sweden",
    }

    response = await client.put(
        f"/admin/tenants/{tenant_id}/credentials/azure",
        json=azure_config,
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    data = response.json()
    assert data["provider"] == "azure"
    assert data["masked_key"] == "azu...def", "Azure key should be masked"
    assert data["config"]["endpoint"] == "https://sweden.openai.azure.com/"
    assert data["config"]["api_version"] == "2024-02-15-preview"
    assert data["config"]["deployment_name"] == "gpt-4-sweden"
    assert "api_key" not in data, "API key should not be in response"

    # Verify in database
    from intric.tenants.tenant_repo import TenantRepo

    repo = TenantRepo(async_session)
    tenant = await repo.get_by_id(tenant_id)

    assert "azure" in tenant.api_credentials
    azure_cred = tenant.api_credentials["azure"]
    assert azure_cred["api_key"] == "azure-key-sweden-456def"
    assert azure_cred["endpoint"] == "https://sweden.openai.azure.com/"
    assert azure_cred["api_version"] == "2024-02-15-preview"
    assert azure_cred["deployment_name"] == "gpt-4-sweden"

    # Test credential resolution with Azure
    from intric.settings.credential_resolver import CredentialResolver

    resolver = CredentialResolver(tenant=tenant)
    azure_key = resolver.get_api_key("azure")
    azure_endpoint = resolver.get_config("azure", "endpoint")

    assert azure_key == "azure-key-sweden-456def"
    assert azure_endpoint == "https://sweden.openai.azure.com/"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_provider_configuration(
    client: AsyncClient,
    async_session: AsyncSession,
    test_tenant,
    super_admin_token: str,
):
    """
    Story 3: Multi-provider configuration and management.

    Scenario:
    - Admin configures multiple LLM providers (OpenAI, Anthropic, Mistral)
    - All credentials stored separately
    - List endpoint shows all providers
    - Individual provider can be deleted without affecting others

    Expected to FAIL: Multi-provider endpoints not implemented.
    """
    tenant_id = test_tenant.id

    # Set multiple providers
    providers = [
        ("openai", {"api_key": "sk-openai-key-multi-123"}),
        ("anthropic", {"api_key": "sk-ant-anthropic-456"}),
        ("mistral", {"api_key": "mistral-key-789"}),
    ]

    for provider, creds in providers:
        response = await client.put(
            f"/admin/tenants/{tenant_id}/credentials/{provider}",
            json=creds,
            headers={"Authorization": f"Bearer {super_admin_token}"},
        )
        assert response.status_code == 200, f"Failed to set {provider}: {response.text}"
        data = response.json()
        assert data["provider"] == provider
        assert "masked_key" in data
        assert "api_key" not in data

    # List all providers
    response = await client.get(
        f"/admin/tenants/{tenant_id}/credentials",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 200

    data = response.json()
    creds = data["credentials"]
    assert len(creds) == 3, f"Expected 3 providers, got {len(creds)}"

    provider_names = {c["provider"] for c in creds}
    assert provider_names == {"openai", "anthropic", "mistral"}

    # Verify each credential is masked
    for cred in creds:
        assert "masked_key" in cred
        assert "api_key" not in cred
        assert cred["masked_key"] is not None

    # Verify in database
    from intric.tenants.tenant_repo import TenantRepo

    repo = TenantRepo(async_session)
    tenant = await repo.get_by_id(tenant_id)

    assert len(tenant.api_credentials) == 3
    assert "openai" in tenant.api_credentials
    assert "anthropic" in tenant.api_credentials
    assert "mistral" in tenant.api_credentials

    # Delete one provider
    response = await client.delete(
        f"/admin/tenants/{tenant_id}/credentials/mistral",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 200

    delete_data = response.json()
    assert delete_data["deleted"] is True
    assert delete_data["provider"] == "mistral"

    # Verify only 2 remain
    response = await client.get(
        f"/admin/tenants/{tenant_id}/credentials",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 200

    creds = response.json()["credentials"]
    assert len(creds) == 2, "Should have 2 providers after deletion"

    remaining_providers = {c["provider"] for c in creds}
    assert remaining_providers == {"openai", "anthropic"}
    assert "mistral" not in remaining_providers

    # Verify in database
    await async_session.refresh(tenant)
    tenant = await repo.get_by_id(tenant_id)
    assert len(tenant.api_credentials) == 2
    assert "mistral" not in tenant.api_credentials


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backward_compatibility(
    client: AsyncClient,
    async_session: AsyncSession,
    test_tenant,
    super_admin_token: str,
    monkeypatch,
):
    """
    Story 4: Backward compatibility - tenants without custom keys use global.

    Scenario:
    - Tenant has no custom credentials configured
    - System falls back to global OPENAI_API_KEY from environment
    - LLM requests work seamlessly
    - No migration required for existing tenants

    Expected to FAIL: CredentialResolver not implemented yet.
    """
    tenant_id = test_tenant.id

    # Ensure tenant has no credentials
    response = await client.get(
        f"/admin/tenants/{tenant_id}/credentials",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["credentials"] == [], "Tenant should have no custom credentials"

    # Set global API key in environment
    global_key = "sk-global-key-789abc"
    monkeypatch.setenv("OPENAI_API_KEY", global_key)

    # Test credential resolution with global key
    from intric.settings.credential_resolver import CredentialResolver
    from intric.tenants.tenant_repo import TenantRepo

    repo = TenantRepo(async_session)
    tenant = await repo.get_by_id(tenant_id)

    resolver = CredentialResolver(tenant=tenant)
    api_key = resolver.get_api_key("openai")

    assert api_key == global_key, "Should fall back to global key"

    # Verify fallback indicator
    uses_global = resolver.uses_global_credentials("openai")
    assert uses_global is True, "Should indicate using global credentials"

    # Now set tenant-specific key
    response = await client.put(
        f"/admin/tenants/{tenant_id}/credentials/openai",
        json={"api_key": "sk-tenant-override-key"},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 200

    # Refresh tenant and test resolution again
    await async_session.refresh(tenant)
    tenant = await repo.get_by_id(tenant_id)

    resolver = CredentialResolver(tenant=tenant)
    api_key = resolver.get_api_key("openai")

    assert api_key == "sk-tenant-override-key", "Should use tenant-specific key"

    uses_global = resolver.uses_global_credentials("openai")
    assert uses_global is False, "Should NOT use global credentials when tenant key exists"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_strict_error_handling_no_fallback(
    client: AsyncClient,
    async_session: AsyncSession,
    test_tenant,
    super_admin_token: str,
    tenant_user_token: str,
    mocker,
):
    """
    Edge Case 1: Invalid tenant credential does NOT fall back to global.

    Scenario:
    - Tenant has invalid API key configured
    - LLM request fails with 401 AuthenticationError
    - System does NOT silently fall back to global key
    - Error is propagated to user
    - Admin can delete invalid credential to restore global fallback

    Expected to FAIL: Strict error handling not implemented.
    """
    tenant_id = test_tenant.id

    # Set invalid API key
    invalid_key = "sk-invalid-key-will-fail-auth"
    response = await client.put(
        f"/admin/tenants/{tenant_id}/credentials/openai",
        json={"api_key": invalid_key},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["masked_key"] == "sk-...auth"

    # Mock LiteLLM to raise AuthenticationError
    from litellm.exceptions import AuthenticationError

    mock_completion = mocker.patch("litellm.acompletion")
    mock_completion.side_effect = AuthenticationError("Invalid API key provided")

    # Make LLM request via chat completion endpoint
    response = await client.post(
        "/api/v1/chat/completions",
        json={
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "test message"}],
        },
        headers={"Authorization": f"Bearer {tenant_user_token}"},
    )

    # CRITICAL: Must return 401, NOT 200 (no silent fallback)
    assert response.status_code == 401, (
        "Should fail with 401 when tenant credential is invalid. "
        "Silent fallback to global key is NOT allowed."
    )

    error_data = response.json()
    assert "detail" in error_data
    assert "invalid" in error_data["detail"].lower() or "authentication" in error_data["detail"].lower()

    # Verify CredentialResolver does NOT fall back
    from intric.settings.credential_resolver import CredentialResolver
    from intric.tenants.tenant_repo import TenantRepo

    repo = TenantRepo(async_session)
    tenant = await repo.get_by_id(tenant_id)

    resolver = CredentialResolver(tenant=tenant)
    resolved_key = resolver.get_api_key("openai")

    # Should return the tenant's invalid key, NOT global fallback
    assert resolved_key == invalid_key, "Should NOT fall back to global key"

    uses_global = resolver.uses_global_credentials("openai")
    assert uses_global is False, "Should indicate using tenant credentials (even if invalid)"

    # Delete invalid credential to restore global fallback
    response = await client.delete(
        f"/admin/tenants/{tenant_id}/credentials/openai",
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 200
    assert response.json()["deleted"] is True

    # Verify credential removed from database
    await async_session.refresh(tenant)
    tenant = await repo.get_by_id(tenant_id)
    assert "openai" not in tenant.api_credentials, "Credential should be deleted"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_credential_update_overwrites_existing(
    client: AsyncClient,
    async_session: AsyncSession,
    test_tenant,
    super_admin_token: str,
):
    """
    Edge Case 2: Updating credential overwrites existing value.

    Scenario:
    - Admin sets initial OpenAI key
    - Admin updates with new key (e.g., key rotation)
    - Old key is completely replaced, not merged
    - Timestamp updated to reflect change

    Expected to FAIL: Update logic not implemented.
    """
    tenant_id = test_tenant.id

    # Set initial key
    initial_key = "sk-initial-key-111"
    response = await client.put(
        f"/admin/tenants/{tenant_id}/credentials/openai",
        json={"api_key": initial_key},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 200
    initial_set_at = response.json()["set_at"]

    # Wait briefly to ensure timestamp changes
    import asyncio
    await asyncio.sleep(0.1)

    # Update with new key
    new_key = "sk-rotated-key-222"
    response = await client.put(
        f"/admin/tenants/{tenant_id}/credentials/openai",
        json={"api_key": new_key},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["masked_key"] == "sk-...222"
    assert data["set_at"] != initial_set_at, "Timestamp should be updated"

    # Verify in database
    from intric.tenants.tenant_repo import TenantRepo

    repo = TenantRepo(async_session)
    tenant = await repo.get_by_id(tenant_id)

    openai_cred = tenant.api_credentials["openai"]
    assert openai_cred["api_key"] == new_key, "Should have new key"
    assert openai_cred["api_key"] != initial_key, "Old key should be gone"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_credential_validation_rejects_invalid_format(
    client: AsyncClient,
    test_tenant,
    super_admin_token: str,
):
    """
    Edge Case 3: Credential validation rejects invalid formats.

    Scenario:
    - Admin attempts to set malformed API key
    - Validation rejects with clear error message
    - No partial data saved to database

    Expected to FAIL: Validation not implemented.
    """
    tenant_id = test_tenant.id

    # Test empty API key
    response = await client.put(
        f"/admin/tenants/{tenant_id}/credentials/openai",
        json={"api_key": ""},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 422, "Should reject empty API key"

    # Test missing api_key field
    response = await client.put(
        f"/admin/tenants/{tenant_id}/credentials/openai",
        json={},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 422, "Should reject missing api_key"

    # Test Azure without required fields
    response = await client.put(
        f"/admin/tenants/{tenant_id}/credentials/azure",
        json={"api_key": "azure-key"},  # Missing endpoint, api_version
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 422, "Should reject Azure credential without endpoint"

    error_data = response.json()
    assert "endpoint" in str(error_data).lower() or "required" in str(error_data).lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unauthorized_access_to_credentials(
    client: AsyncClient,
    test_tenant,
    tenant_user_token: str,
):
    """
    Security: Regular users cannot access credential management endpoints.

    Scenario:
    - Regular user (non-admin) attempts to view credentials
    - Regular user attempts to set credentials
    - All requests rejected with 403 Forbidden

    Expected to FAIL: Authorization not implemented.
    """
    tenant_id = test_tenant.id

    # Attempt to list credentials as regular user
    response = await client.get(
        f"/admin/tenants/{tenant_id}/credentials",
        headers={"Authorization": f"Bearer {tenant_user_token}"},
    )
    assert response.status_code == 403, "Regular user should not access credentials"

    # Attempt to set credential as regular user
    response = await client.put(
        f"/admin/tenants/{tenant_id}/credentials/openai",
        json={"api_key": "sk-unauthorized-attempt"},
        headers={"Authorization": f"Bearer {tenant_user_token}"},
    )
    assert response.status_code == 403, "Regular user should not set credentials"

    # Attempt to delete credential as regular user
    response = await client.delete(
        f"/admin/tenants/{tenant_id}/credentials/openai",
        headers={"Authorization": f"Bearer {tenant_user_token}"},
    )
    assert response.status_code == 403, "Regular user should not delete credentials"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cross_tenant_credential_isolation(
    client: AsyncClient,
    async_session: AsyncSession,
    test_tenant,
    super_admin_token: str,
):
    """
    Security: Tenants cannot access each other's credentials.

    Scenario:
    - Create two tenants with different credentials
    - Verify each tenant only resolves their own credentials
    - Database queries filtered by tenant_id

    Expected to FAIL: Tenant isolation not implemented.
    """
    tenant1_id = test_tenant.id

    # Create second tenant
    from intric.tenants.domain.tenant import Tenant as TenantDomain

    tenant2 = TenantDomain(
        name="Second Municipality",
        slug="second-muni",
    )

    async with async_session.begin():
        async_session.add(tenant2)
        await async_session.flush()
        await async_session.refresh(tenant2)

    tenant2_id = tenant2.id

    # Set different keys for each tenant
    response = await client.put(
        f"/admin/tenants/{tenant1_id}/credentials/openai",
        json={"api_key": "sk-tenant1-key-abc"},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 200

    response = await client.put(
        f"/admin/tenants/{tenant2_id}/credentials/openai",
        json={"api_key": "sk-tenant2-key-xyz"},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert response.status_code == 200

    # Verify credential isolation via CredentialResolver
    from intric.settings.credential_resolver import CredentialResolver
    from intric.tenants.tenant_repo import TenantRepo

    repo = TenantRepo(async_session)

    tenant1 = await repo.get_by_id(tenant1_id)
    resolver1 = CredentialResolver(tenant=tenant1)
    key1 = resolver1.get_api_key("openai")
    assert key1 == "sk-tenant1-key-abc"

    tenant2 = await repo.get_by_id(tenant2_id)
    resolver2 = CredentialResolver(tenant=tenant2)
    key2 = resolver2.get_api_key("openai")
    assert key2 == "sk-tenant2-key-xyz"

    # Verify keys are different
    assert key1 != key2, "Tenants should have isolated credentials"
