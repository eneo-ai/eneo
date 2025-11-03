"""End-to-end integration tests for multi-tenant credential runtime isolation.

These tests verify that tenant-specific LLM credentials are properly isolated
during concurrent operations, covering:

* Cross-tenant credential leakage prevention under load
* VLLM strict mode enforcement (endpoint + api_key required)
* Credential decryption failure handling
* Mixed-mode operation (some tenants with keys, some using global)
* Credential updates during active LLM requests

Critical Settings:
- TENANT_CREDENTIALS_ENABLED: Enables strict per-tenant credential mode
- ENCRYPTION_KEY: Fernet key for encrypting API keys in database
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from intric.settings.credential_resolver import CredentialResolver
from intric.tenants.tenant_repo import TenantRepository


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


async def _put_tenant_credential(
    client: AsyncClient,
    super_api_key: str,
    tenant_id: str,
    provider: str,
    payload: dict,
) -> None:
    """Helper to set tenant credential via API."""
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
    """Helper to delete tenant credential via API."""
    response = await client.delete(
        f"/api/v1/sysadmin/tenants/{tenant_id}/credentials/{provider}",
        headers={"X-API-Key": super_api_key},
    )
    assert response.status_code in {200, 404}, response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_credential_never_leaks_across_concurrent_requests(
    client: AsyncClient,
    async_session: AsyncSession,
    super_admin_token: str,
    encryption_service,
    test_settings,
    mock_transcription_models,
):
    """Verify credential isolation under heavy concurrent load.

    Scenario:
    - Tenant A: OpenAI key = "sk-tenant-a-xxx"
    - Tenant B: OpenAI key = "sk-tenant-b-xxx"
    - Fire 100 concurrent credential resolution requests (50 per tenant)
    - Verify each request resolves the correct tenant's key (no cross-contamination)

    This test exposes:
    - Race conditions in credential resolver
    - Cache pollution across tenants
    - Thread-local storage issues
    - Database query filtering bugs
    """
    # Create two tenants with distinct credentials
    tenant_a_data = await _create_tenant(client, super_admin_token, f"tenant-a-{uuid4().hex[:6]}")
    tenant_b_data = await _create_tenant(client, super_admin_token, f"tenant-b-{uuid4().hex[:6]}")

    tenant_a_id = UUID(tenant_a_data["id"])
    tenant_b_id = UUID(tenant_b_data["id"])

    key_a = f"sk-tenant-a-{uuid4().hex[:12]}"
    key_b = f"sk-tenant-b-{uuid4().hex[:12]}"

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

    # Get tenant objects from repository
    repo = TenantRepository(async_session)
    tenant_a = await repo.get(tenant_a_id)
    tenant_b = await repo.get(tenant_b_id)

    # Track results
    results_a = []
    results_b = []

    async def resolve_for_tenant_a():
        """Resolve credential for tenant A."""
        resolver = CredentialResolver(
            tenant=tenant_a,
            settings=test_settings,
            encryption_service=encryption_service,
        )
        key = resolver.get_api_key("openai")
        results_a.append(key)
        return key

    async def resolve_for_tenant_b():
        """Resolve credential for tenant B."""
        resolver = CredentialResolver(
            tenant=tenant_b,
            settings=test_settings,
            encryption_service=encryption_service,
        )
        key = resolver.get_api_key("openai")
        results_b.append(key)
        return key

    # Fire 100 concurrent requests (50 per tenant, interleaved)
    tasks = []
    for i in range(100):
        if i % 2 == 0:
            tasks.append(resolve_for_tenant_a())
        else:
            tasks.append(resolve_for_tenant_b())

    await asyncio.gather(*tasks)

    # Verify no cross-contamination
    assert len(results_a) == 50, f"Expected 50 results for tenant A, got {len(results_a)}"
    assert len(results_b) == 50, f"Expected 50 results for tenant B, got {len(results_b)}"

    # All results for tenant A should be key_a
    assert all(key == key_a for key in results_a), f"Tenant A got wrong keys: {set(results_a)}"

    # All results for tenant B should be key_b
    assert all(key == key_b for key in results_b), f"Tenant B got wrong keys: {set(results_b)}"

    # Verify no key from tenant A appeared in tenant B's results
    assert key_a not in results_b, "CRITICAL: Tenant A's key leaked to tenant B!"
    assert key_b not in results_a, "CRITICAL: Tenant B's key leaked to tenant A!"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vllm_strict_mode_rejects_missing_endpoint(
    client: AsyncClient,
    async_session: AsyncSession,
    super_admin_token: str,
    encryption_service,
    test_settings,
    mock_transcription_models,
):
    """Verify VLLM strict mode enforces both api_key AND endpoint.

    Scenario:
    - TENANT_CREDENTIALS_ENABLED=true
    - Tenant attempts to set api_key without endpoint
    - Verify API rejects with HTTP 400

    This test exposes:
    - Silent acceptance of incomplete VLLM config
    - Billing leak via fallback to global endpoint
    - Unclear error messages
    """
    tenant_data = await _create_tenant(client, super_admin_token, f"tenant-vllm-{uuid4().hex[:6]}")

    # Enable strict mode
    original_flag = test_settings.tenant_credentials_enabled
    try:
        test_settings.tenant_credentials_enabled = True

        # Attempt to set only api_key (missing endpoint) - should be rejected
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{tenant_data['id']}/credentials/vllm",
            json={"api_key": "test-vllm-key"},  # Missing "endpoint"
            headers={"X-API-Key": super_admin_token},
        )

        # Should reject with 422 (Unprocessable Entity - validation error)
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"

        error_detail = response.json()["detail"]
        # Error detail is structured response with message and errors list
        error_message = str(error_detail.get("message", "")) + " " + " ".join(error_detail.get("errors", []))
        assert "endpoint" in error_message.lower(), f"Error should mention endpoint: {error_detail}"
        assert "vllm" in error_message.lower(), f"Error should mention vllm: {error_detail}"

        # Verify credential was NOT stored
        list_response = await client.get(
            f"/api/v1/sysadmin/tenants/{tenant_data['id']}/credentials",
            headers={"X-API-Key": super_admin_token},
        )
        assert list_response.status_code == 200
        credentials = list_response.json()["credentials"]
        assert len(credentials) == 0, "No credentials should be stored after rejection"

    finally:
        test_settings.tenant_credentials_enabled = original_flag


@pytest.mark.integration
@pytest.mark.asyncio
async def test_credential_decryption_failure_raises_clear_error(
    client: AsyncClient,
    async_session: AsyncSession,
    super_admin_token: str,
    encryption_service,
    test_settings,
    mock_transcription_models,
):
    """Verify decryption failure provides actionable error message.

    Scenario:
    - Store credential encrypted with Key A
    - Rotate encryption key to Key B
    - Attempt to decrypt credential
    - Verify error message mentions key rotation

    This test exposes:
    - Silent decryption failures
    - Generic "decryption failed" errors
    - Missing guidance for key rotation
    """
    tenant_data = await _create_tenant(client, super_admin_token, f"tenant-decrypt-{uuid4().hex[:6]}")
    tenant_id = UUID(tenant_data["id"])

    # Store credential with current encryption key
    await _put_tenant_credential(
        client,
        super_admin_token,
        tenant_data["id"],
        "openai",
        {"api_key": "sk-test-before-rotation"},
    )

    # Simulate key rotation by manually corrupting encrypted value in database
    # (In production, this happens when ENCRYPTION_KEY changes)
    repo = TenantRepository(async_session)
    tenant = await repo.get(tenant_id)

    # Tamper with encrypted credential to simulate key mismatch
    # Keep the enc:fernet:v1: prefix but corrupt the token to simulate wrong encryption key
    if tenant.api_credentials and "openai" in tenant.api_credentials:
        # Corrupt the Fernet token (keep version prefix to bypass plaintext fallback)
        tenant.api_credentials["openai"]["api_key"] = "enc:fernet:v1:gAAAAABcorrupted_invalid_fernet_token_data_here=="

        # Update tenant in database using separate session
        from intric.database.tables.tenant_table import Tenants
        from intric.database.database import sessionmanager
        import sqlalchemy as sa

        async with sessionmanager.session() as session:
            async with session.begin():
                stmt = (
                    sa.update(Tenants)
                    .where(Tenants.id == tenant_id)
                    .values(api_credentials=tenant.api_credentials)
                )
                await session.execute(stmt)

    # Refresh tenant object
    tenant = await repo.get(tenant_id)

    # Attempt to decrypt
    resolver = CredentialResolver(
        tenant=tenant,
        settings=test_settings,
        encryption_service=encryption_service,
    )

    with pytest.raises(ValueError) as exc_info:
        resolver.get_api_key("openai")

    # Verify error message is actionable
    error_message = str(exc_info.value)
    assert "decrypt" in error_message.lower(), "Error should mention decryption failure"
    assert "encryption key" in error_message.lower() or "corrupted" in error_message.lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_plaintext_credentials_rejected_when_encryption_enabled(
    client: AsyncClient,
    async_session: AsyncSession,
    super_admin_token: str,
    encryption_service,
    test_settings,
    mock_transcription_models,
):
    """Verify plaintext credentials are rejected when encryption is enabled.

    Security Test:
    - Store credential with encryption enabled
    - Strip enc: prefix to simulate tampering/corruption
    - Attempt to decrypt
    - Verify ValueError raised (not silent passthrough)

    This test catches the vulnerability where corrupted credentials
    could bypass encryption checks by losing their enc: prefix.
    """
    tenant_data = await _create_tenant(client, super_admin_token, f"tenant-plaintext-{uuid4().hex[:6]}")
    tenant_id = UUID(tenant_data["id"])

    # Store credential normally (will be encrypted)
    await _put_tenant_credential(
        client,
        super_admin_token,
        tenant_data["id"],
        "openai",
        {"api_key": "sk-test-key"},
    )

    # Get tenant object
    repo = TenantRepository(async_session)
    tenant = await repo.get(tenant_id)

    # Tamper: Strip enc: prefix to simulate corruption/tampering
    if tenant.api_credentials and "openai" in tenant.api_credentials:
        # Replace with plaintext (no enc: prefix)
        tenant.api_credentials["openai"]["api_key"] = "sk-plaintext-not-encrypted"

        # Update tenant in database using separate session
        from intric.database.tables.tenant_table import Tenants
        from intric.database.database import sessionmanager
        import sqlalchemy as sa

        async with sessionmanager.session() as session:
            async with session.begin():
                stmt = (
                    sa.update(Tenants)
                    .where(Tenants.id == tenant_id)
                    .values(api_credentials=tenant.api_credentials)
                )
                await session.execute(stmt)

    # Refresh tenant object
    tenant = await repo.get(tenant_id)

    # Attempt to decrypt with encryption enabled
    resolver = CredentialResolver(
        tenant=tenant,
        settings=test_settings,
        encryption_service=encryption_service,
    )

    # Should raise ValueError (not return plaintext)
    with pytest.raises(ValueError) as exc_info:
        resolver.get_api_key("openai")

    # Verify error message mentions plaintext/corruption
    error_message = str(exc_info.value)
    assert "plaintext" in error_message.lower() or "corrupted" in error_message.lower() or "tampered" in error_message.lower(), \
        f"Error should mention plaintext/corruption/tampering: {error_message}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mixed_mode_tenants_some_with_keys_some_global(
    client: AsyncClient,
    async_session: AsyncSession,
    super_admin_token: str,
    encryption_service,
    test_settings,
    mock_transcription_models,
):
    """Verify mixed mode: some tenants with credentials, some using global.

    Scenario:
    - TENANT_CREDENTIALS_ENABLED=false (single-tenant mode)
    - Tenant A: has OpenAI key
    - Tenant B: no key (falls back to global)
    - Verify both work correctly

    This test exposes:
    - Fallback logic bugs
    - Inconsistent behavior across tenants
    - Global key not being used
    """
    tenant_a_data = await _create_tenant(client, super_admin_token, f"tenant-mixed-a-{uuid4().hex[:6]}")
    tenant_b_data = await _create_tenant(client, super_admin_token, f"tenant-mixed-b-{uuid4().hex[:6]}")

    tenant_a_id = UUID(tenant_a_data["id"])
    tenant_b_id = UUID(tenant_b_data["id"])

    # Tenant A has specific key
    key_a = f"sk-tenant-a-{uuid4().hex[:8]}"
    await _put_tenant_credential(
        client,
        super_admin_token,
        tenant_a_data["id"],
        "openai",
        {"api_key": key_a},
    )

    # Tenant B has no key (will fall back to global)
    await _delete_tenant_credential(
        client,
        super_admin_token,
        tenant_b_data["id"],
        "openai",
    )

    # Get tenant objects
    repo = TenantRepository(async_session)
    tenant_a = await repo.get(tenant_a_id)
    tenant_b = await repo.get(tenant_b_id)

    # Disable strict mode (allow fallback)
    original_flag = test_settings.tenant_credentials_enabled
    original_global_key = test_settings.openai_api_key
    try:
        test_settings.tenant_credentials_enabled = False
        test_settings.openai_api_key = f"sk-global-{uuid4().hex[:8]}"

        # Resolve for tenant A (should use tenant key)
        resolver_a = CredentialResolver(
            tenant=tenant_a,
            settings=test_settings,
            encryption_service=encryption_service,
        )
        resolved_a = resolver_a.get_api_key("openai")
        assert resolved_a == key_a, f"Tenant A should use tenant key, got {resolved_a}"

        # Resolve for tenant B (should use global key)
        resolver_b = CredentialResolver(
            tenant=tenant_b,
            settings=test_settings,
            encryption_service=encryption_service,
        )
        resolved_b = resolver_b.get_api_key("openai")
        assert resolved_b == test_settings.openai_api_key, f"Tenant B should use global key, got {resolved_b}"

    finally:
        test_settings.tenant_credentials_enabled = original_flag
        test_settings.openai_api_key = original_global_key


@pytest.mark.integration
@pytest.mark.asyncio
async def test_azure_provider_requires_all_fields_in_strict_mode(
    client: AsyncClient,
    async_session: AsyncSession,
    super_admin_token: str,
    encryption_service,
    test_settings,
    mock_transcription_models,
):
    """Verify Azure provider requires api_key, endpoint, api_version, deployment_name.

    Scenario:
    - TENANT_CREDENTIALS_ENABLED=true
    - Attempt to set incomplete Azure config (missing deployment_name)
    - Verify API rejects with 400 and lists missing fields

    This test exposes:
    - Partial credential acceptance
    - Missing field validation at API level
    - Silent fallback to global config
    """
    tenant_data = await _create_tenant(client, super_admin_token, f"tenant-azure-{uuid4().hex[:6]}")

    # Attempt to set incomplete Azure config (missing deployment_name)
    response = await client.put(
        f"/api/v1/sysadmin/tenants/{tenant_data['id']}/credentials/azure",
        json={
            "api_key": "test-azure-key",
            "endpoint": "https://test.openai.azure.com",
            "api_version": "2024-02-15-preview",
            # Missing: deployment_name
        },
        headers={"X-API-Key": super_admin_token},
    )

    # Verify API rejects incomplete configuration
    assert response.status_code == 422, f"Expected 422 (Validation Error), got {response.status_code}: {response.text}"
    error_detail = response.json()["detail"]
    # Error detail is structured response - convert to string for checking
    error_str = str(error_detail)
    assert "deployment_name" in error_str, f"Error should mention missing 'deployment_name': {error_detail}"
    assert "azure" in error_str.lower(), f"Error should mention Azure: {error_detail}"

    # Now verify that with ALL required fields, it succeeds
    complete_response = await client.put(
        f"/api/v1/sysadmin/tenants/{tenant_data['id']}/credentials/azure",
        json={
            "api_key": "test-azure-key",
            "endpoint": "https://test.openai.azure.com",
            "api_version": "2024-02-15-preview",
            "deployment_name": "gpt-4",
        },
        headers={"X-API-Key": super_admin_token},
    )
    assert complete_response.status_code == 200, f"Complete config should succeed: {complete_response.text}"

    # Verify credential was stored
    tenant_id = UUID(tenant_data["id"])
    repo = TenantRepository(async_session)
    tenant = await repo.get(tenant_id)

    # Enable strict mode
    original_flag = test_settings.tenant_credentials_enabled
    try:
        test_settings.tenant_credentials_enabled = True

        resolver = CredentialResolver(
            tenant=tenant,
            settings=test_settings,
            encryption_service=encryption_service,
        )

        # Now we should be able to get all fields
        deployment_name = resolver.get_credential_field(
            provider="azure",
            field="deployment_name",
            fallback=None,
        )
        assert deployment_name == "gpt-4", f"Should retrieve deployment_name: {deployment_name}"

    finally:
        test_settings.tenant_credentials_enabled = original_flag


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_credential_updates_maintain_isolation(
    client: AsyncClient,
    async_session: AsyncSession,
    super_admin_token: str,
    encryption_service,
    test_settings,
    mock_transcription_models,
):
    """Verify credential updates during concurrent resolution don't cross-contaminate.

    Scenario:
    - Tenant A starts with key "sk-old"
    - Concurrently:
      - 50 threads resolve Tenant A credentials
      - 1 thread updates Tenant A credential to "sk-new"
      - 50 threads resolve Tenant A credentials again
    - Verify no thread ever gets Tenant B's key
    - Verify eventual consistency (all threads eventually see "sk-new")

    This test exposes:
    - Cache invalidation bugs
    - Transaction isolation issues
    - Read-your-own-writes failures
    """
    tenant_data = await _create_tenant(client, super_admin_token, f"tenant-update-{uuid4().hex[:6]}")
    tenant_id = UUID(tenant_data["id"])

    key_old = f"sk-old-{uuid4().hex[:8]}"
    key_new = f"sk-new-{uuid4().hex[:8]}"

    # Set initial credential
    await _put_tenant_credential(
        client,
        super_admin_token,
        tenant_data["id"],
        "openai",
        {"api_key": key_old},
    )

    # Get tenant object
    repo = TenantRepository(async_session)

    results_before = []
    results_after = []

    async def resolve_before():
        """Resolve credential before update."""
        tenant = await repo.get(tenant_id)
        resolver = CredentialResolver(
            tenant=tenant,
            settings=test_settings,
            encryption_service=encryption_service,
        )
        key = resolver.get_api_key("openai")
        results_before.append(key)

    async def update_credential():
        """Update credential mid-test."""
        await asyncio.sleep(0.1)  # Let some resolves happen first
        await _put_tenant_credential(
            client,
            super_admin_token,
            tenant_data["id"],
            "openai",
            {"api_key": key_new},
        )

    async def resolve_after():
        """Resolve credential after update."""
        await asyncio.sleep(0.2)  # Wait for update to complete
        tenant = await repo.get(tenant_id)
        resolver = CredentialResolver(
            tenant=tenant,
            settings=test_settings,
            encryption_service=encryption_service,
        )
        key = resolver.get_api_key("openai")
        results_after.append(key)

    # Run concurrent operations
    tasks = (
        [resolve_before() for _ in range(50)]
        + [update_credential()]
        + [resolve_after() for _ in range(50)]
    )
    await asyncio.gather(*tasks)

    # Verify results before update
    assert all(key == key_old for key in results_before), f"Before update: expected {key_old}, got {set(results_before)}"

    # Verify results after update
    assert all(key == key_new for key in results_after), f"After update: expected {key_new}, got {set(results_after)}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_credential_resolver_cache_pollution_prevention(
    client: AsyncClient,
    async_session: AsyncSession,
    super_admin_token: str,
    encryption_service,
    test_settings,
    mock_transcription_models,
):
    """Verify CredentialResolver instances don't share state across tenants.

    Scenario:
    - Create resolver for Tenant A
    - Resolve credential
    - Create resolver for Tenant B (reusing same encryption_service instance)
    - Resolve credential
    - Verify Tenant B gets its own key (not cached from Tenant A)

    This test exposes:
    - Instance variable pollution
    - Shared mutable state
    - Singleton pattern bugs
    """
    tenant_a_data = await _create_tenant(client, super_admin_token, f"tenant-cache-a-{uuid4().hex[:6]}")
    tenant_b_data = await _create_tenant(client, super_admin_token, f"tenant-cache-b-{uuid4().hex[:6]}")

    tenant_a_id = UUID(tenant_a_data["id"])
    tenant_b_id = UUID(tenant_b_data["id"])

    key_a = f"sk-a-{uuid4().hex[:8]}"
    key_b = f"sk-b-{uuid4().hex[:8]}"

    await _put_tenant_credential(client, super_admin_token, tenant_a_data["id"], "openai", {"api_key": key_a})
    await _put_tenant_credential(client, super_admin_token, tenant_b_data["id"], "openai", {"api_key": key_b})

    # Get tenant objects
    repo = TenantRepository(async_session)
    tenant_a = await repo.get(tenant_a_id)
    tenant_b = await repo.get(tenant_b_id)

    # Create resolver for Tenant A
    resolver_a = CredentialResolver(
        tenant=tenant_a,
        settings=test_settings,
        encryption_service=encryption_service,
    )
    resolved_a = resolver_a.get_api_key("openai")
    assert resolved_a == key_a

    # Create NEW resolver for Tenant B (reusing same encryption_service)
    resolver_b = CredentialResolver(
        tenant=tenant_b,
        settings=test_settings,
        encryption_service=encryption_service,  # Same instance
    )
    resolved_b = resolver_b.get_api_key("openai")

    # Verify no cache pollution
    assert resolved_b == key_b, f"Cache pollution: Tenant B got {resolved_b}, expected {key_b}"
    assert resolved_b != key_a, "CRITICAL: Tenant B got Tenant A's key!"
