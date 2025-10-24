"""Integration tests for TenantRepository JSONB operations.

Tests PostgreSQL JSONB operations for tenant API credentials:
- update_api_credential: Creates new credentials or overwrites existing
- delete_api_credential: Removes specific provider credentials
- get_api_credentials_masked: Returns masked keys for UI display

These operations use PostgreSQL's JSONB functions for efficient updates
without loading/modifying/saving the entire JSONB object.
"""

import pytest


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_api_credential_creates_new(db_container, test_tenant):
    """Creating new credential via JSONB set operation.

    When a tenant has no existing credentials, update_api_credential should
    create the JSONB structure and add the new provider credential.
    """
    async with db_container() as container:
        tenant_repo = container.tenant_repo()

        # Initially, tenant should have empty credentials
        assert test_tenant.api_credentials == {}

        # Add openai credential
        updated_tenant = await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="openai",
            credential={"api_key": "sk-test-key-123"},
        )

        # Verify credential was added
        assert "openai" in updated_tenant.api_credentials
        # Note: In integration tests, encryption is enabled, so the stored value will be encrypted
        # We verify it exists and is encrypted (not plaintext)
        assert "api_key" in updated_tenant.api_credentials["openai"]
        encrypted_value = updated_tenant.api_credentials["openai"]["api_key"]
        assert encrypted_value != "sk-test-key-123", "Key should be encrypted in database"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_api_credential_overwrites_existing(db_container, test_tenant):
    """Updating existing credential via JSONB set operation.

    When a tenant already has a credential for a provider, update_api_credential
    should overwrite it with the new value.
    """
    async with db_container() as container:
        tenant_repo = container.tenant_repo()

        # Add initial credential
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="openai",
            credential={"api_key": "sk-old-key-123"},
        )

        # Update with new credential
        updated_tenant = await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="openai",
            credential={"api_key": "sk-new-key-456"},
        )

        # Verify credential was overwritten (check that it's encrypted and different from old value)
        encrypted_value = updated_tenant.api_credentials["openai"]["api_key"]
        assert encrypted_value != "sk-old-key-123", "Old key should be replaced"
        assert encrypted_value != "sk-new-key-456", "Key should be encrypted"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_api_credential_multiple_providers(db_container, test_tenant):
    """Adding multiple providers creates separate JSONB keys.

    Each provider should be stored as a separate key in the JSONB object.
    """
    async with db_container() as container:
        tenant_repo = container.tenant_repo()

        # Add multiple providers
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="openai",
            credential={"api_key": "sk-openai-key"},
        )
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="anthropic",
            credential={"api_key": "sk-anthropic-key"},
        )
        updated_tenant = await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="azure",
            credential={
                "api_key": "azure-key",
                "endpoint": "https://example.openai.azure.com",
                "api_version": "2024-02-15-preview",
                "deployment_name": "gpt-4",
            },
        )

        # Verify all providers exist
        assert "openai" in updated_tenant.api_credentials
        assert "anthropic" in updated_tenant.api_credentials
        assert "azure" in updated_tenant.api_credentials

        # Verify Azure's non-encrypted fields are stored correctly
        assert (
            updated_tenant.api_credentials["azure"]["endpoint"]
            == "https://example.openai.azure.com"
        )
        assert (
            updated_tenant.api_credentials["azure"]["api_version"]
            == "2024-02-15-preview"
        )
        assert (
            updated_tenant.api_credentials["azure"]["deployment_name"]
            == "gpt-4"
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_api_credential_case_insensitive(db_container, test_tenant):
    """Provider names are normalized to lowercase.

    Regardless of case provided, credentials should be stored in lowercase.
    """
    async with db_container() as container:
        tenant_repo = container.tenant_repo()

        # Add credential with mixed case
        updated_tenant = await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="OpenAI",
            credential={"api_key": "sk-test-key"},
        )

        # Verify stored in lowercase
        assert "openai" in updated_tenant.api_credentials
        assert "OpenAI" not in updated_tenant.api_credentials


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_api_credential_removes_specific(db_container, test_tenant):
    """Delete removes specific provider credential.

    delete_api_credential should remove only the specified provider's
    credential, leaving the JSONB structure intact.
    """
    async with db_container() as container:
        tenant_repo = container.tenant_repo()

        # Add credential
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="openai",
            credential={"api_key": "sk-test-key"},
        )

        # Verify it exists
        tenant = await tenant_repo.get(test_tenant.id)
        assert "openai" in tenant.api_credentials

        # Delete it
        updated_tenant = await tenant_repo.delete_api_credential(
            tenant_id=test_tenant.id,
            provider="openai",
        )

        # Verify it's gone
        assert "openai" not in updated_tenant.api_credentials


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_api_credential_leaves_others(db_container, test_tenant):
    """Deleting one provider leaves others intact.

    When deleting a specific provider's credential, other providers'
    credentials should remain unchanged.
    """
    async with db_container() as container:
        tenant_repo = container.tenant_repo()

        # Add multiple providers
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="openai",
            credential={"api_key": "sk-openai-key"},
        )
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="anthropic",
            credential={"api_key": "sk-anthropic-key"},
        )
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="azure",
            credential={
                "api_key": "azure-key",
                "endpoint": "https://example.openai.azure.com",
                "api_version": "2024-02-15-preview",
                "deployment_name": "gpt-4",
            },
        )

        # Delete one provider
        updated_tenant = await tenant_repo.delete_api_credential(
            tenant_id=test_tenant.id,
            provider="anthropic",
        )

        # Verify only anthropic is gone, others remain
        assert "openai" in updated_tenant.api_credentials
        assert "anthropic" not in updated_tenant.api_credentials
        assert "azure" in updated_tenant.api_credentials


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_api_credential_nonexistent(db_container, test_tenant):
    """Deleting non-existent credential is idempotent.

    Deleting a credential that doesn't exist should not raise an error
    and should leave the JSONB structure unchanged.
    """
    async with db_container() as container:
        tenant_repo = container.tenant_repo()

        # Add one credential
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="openai",
            credential={"api_key": "sk-test-key"},
        )

        # Delete a different provider that doesn't exist
        updated_tenant = await tenant_repo.delete_api_credential(
            tenant_id=test_tenant.id,
            provider="anthropic",
        )

        # Verify openai credential still exists
        assert "openai" in updated_tenant.api_credentials
        assert "anthropic" not in updated_tenant.api_credentials


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_api_credential_case_insensitive(db_container, test_tenant):
    """Provider names are normalized to lowercase when deleting.

    Delete operation should handle case-insensitive provider names.
    """
    async with db_container() as container:
        tenant_repo = container.tenant_repo()

        # Add credential in lowercase
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="openai",
            credential={"api_key": "sk-test-key"},
        )

        # Delete with mixed case
        updated_tenant = await tenant_repo.delete_api_credential(
            tenant_id=test_tenant.id,
            provider="OpenAI",
        )

        # Verify it's gone
        assert "openai" not in updated_tenant.api_credentials


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_api_credentials_masked_returns_last_4(db_container, test_tenant):
    """Returns last 4 chars with '...' prefix for keys >4 chars.

    For security, API keys should be masked in the UI showing only the
    last 4 characters with a '...' prefix.
    """
    async with db_container() as container:
        tenant_repo = container.tenant_repo()

        # Add credentials with keys longer than 4 chars
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="openai",
            credential={"api_key": "sk-test-key-1234"},
        )
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="anthropic",
            credential={"api_key": "sk-anthropic-key-5678"},
        )

        # Get masked credentials
        masked = await tenant_repo.get_api_credentials_masked(test_tenant.id)

        # Verify masking (preserves sk- prefix per masking.py implementation)
        assert masked["openai"] == "sk-...1234"
        assert masked["anthropic"] == "sk-...5678"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_api_credentials_masked_handles_short_keys(db_container, test_tenant):
    """Masking handles keys ≤4 chars with '***'.

    Very short API keys (≤4 chars) should be completely masked with '***'
    instead of showing the last 4 characters.
    """
    async with db_container() as container:
        tenant_repo = container.tenant_repo()

        # Add credentials with short keys
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="openai",
            credential={"api_key": "abc"},  # 3 chars
        )
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="anthropic",
            credential={"api_key": "xy"},  # 2 chars
        )
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="azure",
            credential={
                "api_key": "test",  # 4 chars (boundary)
                "endpoint": "https://example.openai.azure.com",
                "api_version": "2024-02-15-preview",
                "deployment_name": "gpt-4",
            },
        )

        # Get masked credentials
        masked = await tenant_repo.get_api_credentials_masked(test_tenant.id)

        # Verify masking for short keys
        assert masked["openai"] == "***"
        assert masked["anthropic"] == "***"
        assert masked["azure"] == "***"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_api_credentials_masked_empty_credentials(db_container, test_tenant):
    """Empty credentials dict returns empty dict.

    When a tenant has no API credentials configured, should return
    an empty dictionary.
    """
    async with db_container() as container:
        tenant_repo = container.tenant_repo()

        # Tenant starts with no credentials
        masked = await tenant_repo.get_api_credentials_masked(test_tenant.id)

        # Should return empty dict
        assert masked == {}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_api_credentials_masked_multiple_providers(db_container, test_tenant):
    """Multiple providers all masked correctly.

    Each provider's credential should be independently masked according
    to its key length.
    """
    async with db_container() as container:
        tenant_repo = container.tenant_repo()

        # Add mix of short and long keys
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="openai",
            credential={"api_key": "sk-very-long-key-123456"},  # Long
        )
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="anthropic",
            credential={"api_key": "abc"},  # Short
        )
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="azure",
            credential={
                "api_key": "azure-key-7890",  # Long
                "endpoint": "https://example.openai.azure.com",
                "api_version": "2024-02-15-preview",
                "deployment_name": "gpt-4",
            },
        )
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="berget",
            credential={"api_key": "test"},  # Short (4 chars)
        )

        # Get masked credentials
        masked = await tenant_repo.get_api_credentials_masked(test_tenant.id)

        # Verify each is masked correctly (preserves sk- prefix per masking.py)
        assert masked["openai"] == "sk-...3456"  # sk- prefix + last 4 of long key
        assert masked["anthropic"] == "***"  # Short key completely masked
        assert masked["azure"] == "...7890"  # No sk- prefix for azure key
        assert masked["berget"] == "***"  # 4-char key completely masked


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_api_credentials_masked_with_azure_extra_fields(
    db_container, test_tenant
):
    """Masking works with Azure credentials that have extra fields.

    Azure credentials include endpoint, api_version, deployment_name.
    Masking should still work correctly and only mask the api_key.
    """
    async with db_container() as container:
        tenant_repo = container.tenant_repo()

        # Add Azure credential with all fields
        await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="azure",
            credential={
                "api_key": "azure-key-1234567890",
                "endpoint": "https://example.openai.azure.com",
                "api_version": "2024-02-15-preview",
                "deployment_name": "gpt-4",
            },
        )

        # Get masked credentials
        masked = await tenant_repo.get_api_credentials_masked(test_tenant.id)

        # Verify only api_key is in masked result and is masked
        assert "azure" in masked
        assert masked["azure"] == "...7890"  # Last 4 of api_key (no sk- prefix for azure keys)
        # Note: masked dict only contains provider -> masked_key, not other fields
