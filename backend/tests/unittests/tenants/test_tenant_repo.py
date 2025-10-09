"""Unit tests for TenantRepository JSONB operations.

Tests PostgreSQL JSONB operations for tenant API credentials:
- update_api_credential: Creates new credentials or overwrites existing
- delete_api_credential: Removes specific provider credentials
- get_api_credentials_masked: Returns masked keys for UI display

These operations use PostgreSQL's JSONB functions for efficient updates
without loading/modifying/saving the entire JSONB object.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from intric.database.tables.tenant_table import Tenants
from intric.tenants.tenant_repo import TenantRepository


@pytest.fixture
async def async_session():
    """Create an in-memory SQLite database for testing.

    Note: SQLite doesn't have native JSONB support like PostgreSQL,
    but SQLAlchemy emulates it with JSON columns. This is sufficient
    for unit testing the repository logic.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Tenants.metadata.create_all)

    # Create session factory
    async_session_factory = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def tenant_repo(async_session):
    """TenantRepository instance with async session."""
    return TenantRepository(async_session)


@pytest.fixture
async def sample_tenant(tenant_repo):
    """Create a sample tenant in the database."""
    from intric.tenants.tenant import TenantBase

    tenant_data = TenantBase(
        name="test-tenant",
        display_name="Test Tenant",
        quota_limit=1024**3,
    )

    tenant = await tenant_repo.add(tenant_data)
    return tenant


@pytest.mark.asyncio
async def test_update_api_credential_creates_new(tenant_repo, sample_tenant):
    """Creating new credential via JSONB set operation.

    When a tenant has no existing credentials, update_api_credential should
    create the JSONB structure and add the new provider credential.
    """
    # Initially, tenant should have empty credentials
    assert sample_tenant.api_credentials == {}

    # Add openai credential
    updated_tenant = await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="openai",
        credential={"api_key": "sk-test-key-123"},
    )

    # Verify credential was added
    assert "openai" in updated_tenant.api_credentials
    assert updated_tenant.api_credentials["openai"]["api_key"] == "sk-test-key-123"


@pytest.mark.asyncio
async def test_update_api_credential_overwrites_existing(tenant_repo, sample_tenant):
    """Updating existing credential via JSONB set operation.

    When a tenant already has a credential for a provider, update_api_credential
    should overwrite it with the new value.
    """
    # Add initial credential
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="openai",
        credential={"api_key": "sk-old-key-123"},
    )

    # Update with new credential
    updated_tenant = await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="openai",
        credential={"api_key": "sk-new-key-456"},
    )

    # Verify credential was overwritten
    assert updated_tenant.api_credentials["openai"]["api_key"] == "sk-new-key-456"


@pytest.mark.asyncio
async def test_update_api_credential_multiple_providers(tenant_repo, sample_tenant):
    """Adding multiple providers creates separate JSONB keys.

    Each provider should be stored as a separate key in the JSONB object.
    """
    # Add multiple providers
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="openai",
        credential={"api_key": "sk-openai-key"},
    )
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="anthropic",
        credential={"api_key": "sk-anthropic-key"},
    )
    updated_tenant = await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
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
    assert updated_tenant.api_credentials["openai"]["api_key"] == "sk-openai-key"
    assert (
        updated_tenant.api_credentials["anthropic"]["api_key"] == "sk-anthropic-key"
    )
    assert updated_tenant.api_credentials["azure"]["api_key"] == "azure-key"
    assert (
        updated_tenant.api_credentials["azure"]["endpoint"]
        == "https://example.openai.azure.com"
    )


@pytest.mark.asyncio
async def test_update_api_credential_case_insensitive(tenant_repo, sample_tenant):
    """Provider names are normalized to lowercase.

    Regardless of case provided, credentials should be stored in lowercase.
    """
    # Add credential with mixed case
    updated_tenant = await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="OpenAI",
        credential={"api_key": "sk-test-key"},
    )

    # Verify stored in lowercase
    assert "openai" in updated_tenant.api_credentials
    assert "OpenAI" not in updated_tenant.api_credentials


@pytest.mark.asyncio
async def test_delete_api_credential_removes_specific(tenant_repo, sample_tenant):
    """Delete removes specific provider credential.

    delete_api_credential should remove only the specified provider's
    credential, leaving the JSONB structure intact.
    """
    # Add credential
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="openai",
        credential={"api_key": "sk-test-key"},
    )

    # Verify it exists
    tenant = await tenant_repo.get(sample_tenant.id)
    assert "openai" in tenant.api_credentials

    # Delete it
    updated_tenant = await tenant_repo.delete_api_credential(
        tenant_id=sample_tenant.id,
        provider="openai",
    )

    # Verify it's gone
    assert "openai" not in updated_tenant.api_credentials


@pytest.mark.asyncio
async def test_delete_api_credential_leaves_others(tenant_repo, sample_tenant):
    """Deleting one provider leaves others intact.

    When deleting a specific provider's credential, other providers'
    credentials should remain unchanged.
    """
    # Add multiple providers
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="openai",
        credential={"api_key": "sk-openai-key"},
    )
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="anthropic",
        credential={"api_key": "sk-anthropic-key"},
    )
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="azure",
        credential={"api_key": "azure-key"},
    )

    # Delete one provider
    updated_tenant = await tenant_repo.delete_api_credential(
        tenant_id=sample_tenant.id,
        provider="anthropic",
    )

    # Verify only anthropic is gone, others remain
    assert "openai" in updated_tenant.api_credentials
    assert "anthropic" not in updated_tenant.api_credentials
    assert "azure" in updated_tenant.api_credentials
    assert updated_tenant.api_credentials["openai"]["api_key"] == "sk-openai-key"
    assert updated_tenant.api_credentials["azure"]["api_key"] == "azure-key"


@pytest.mark.asyncio
async def test_delete_api_credential_nonexistent(tenant_repo, sample_tenant):
    """Deleting non-existent credential is idempotent.

    Deleting a credential that doesn't exist should not raise an error
    and should leave the JSONB structure unchanged.
    """
    # Add one credential
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="openai",
        credential={"api_key": "sk-test-key"},
    )

    # Delete a different provider that doesn't exist
    updated_tenant = await tenant_repo.delete_api_credential(
        tenant_id=sample_tenant.id,
        provider="anthropic",
    )

    # Verify openai credential still exists
    assert "openai" in updated_tenant.api_credentials
    assert "anthropic" not in updated_tenant.api_credentials


@pytest.mark.asyncio
async def test_delete_api_credential_case_insensitive(tenant_repo, sample_tenant):
    """Provider names are normalized to lowercase when deleting.

    Delete operation should handle case-insensitive provider names.
    """
    # Add credential in lowercase
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="openai",
        credential={"api_key": "sk-test-key"},
    )

    # Delete with mixed case
    updated_tenant = await tenant_repo.delete_api_credential(
        tenant_id=sample_tenant.id,
        provider="OpenAI",
    )

    # Verify it's gone
    assert "openai" not in updated_tenant.api_credentials


@pytest.mark.asyncio
async def test_get_api_credentials_masked_returns_last_4(tenant_repo, sample_tenant):
    """Returns last 4 chars with '...' prefix for keys >4 chars.

    For security, API keys should be masked in the UI showing only the
    last 4 characters with a '...' prefix.
    """
    # Add credentials with keys longer than 4 chars
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="openai",
        credential={"api_key": "sk-test-key-1234"},
    )
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="anthropic",
        credential={"api_key": "sk-anthropic-key-5678"},
    )

    # Get masked credentials
    masked = await tenant_repo.get_api_credentials_masked(sample_tenant.id)

    # Verify masking
    assert masked["openai"] == "...1234"
    assert masked["anthropic"] == "...5678"


@pytest.mark.asyncio
async def test_get_api_credentials_masked_handles_short_keys(tenant_repo, sample_tenant):
    """Masking handles keys ≤4 chars with '***'.

    Very short API keys (≤4 chars) should be completely masked with '***'
    instead of showing the last 4 characters.
    """
    # Add credentials with short keys
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="openai",
        credential={"api_key": "abc"},  # 3 chars
    )
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="anthropic",
        credential={"api_key": "xy"},  # 2 chars
    )
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="azure",
        credential={"api_key": "test"},  # 4 chars (boundary)
    )

    # Get masked credentials
    masked = await tenant_repo.get_api_credentials_masked(sample_tenant.id)

    # Verify masking for short keys
    assert masked["openai"] == "***"
    assert masked["anthropic"] == "***"
    assert masked["azure"] == "***"


@pytest.mark.asyncio
async def test_get_api_credentials_masked_empty_credentials(tenant_repo, sample_tenant):
    """Empty credentials dict returns empty dict.

    When a tenant has no API credentials configured, should return
    an empty dictionary.
    """
    # Tenant starts with no credentials
    masked = await tenant_repo.get_api_credentials_masked(sample_tenant.id)

    # Should return empty dict
    assert masked == {}


@pytest.mark.asyncio
async def test_get_api_credentials_masked_multiple_providers(tenant_repo, sample_tenant):
    """Multiple providers all masked correctly.

    Each provider's credential should be independently masked according
    to its key length.
    """
    # Add mix of short and long keys
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="openai",
        credential={"api_key": "sk-very-long-key-123456"},  # Long
    )
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="anthropic",
        credential={"api_key": "abc"},  # Short
    )
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="azure",
        credential={"api_key": "azure-key-7890"},  # Long
    )
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="berget",
        credential={"api_key": "test"},  # Short (4 chars)
    )

    # Get masked credentials
    masked = await tenant_repo.get_api_credentials_masked(sample_tenant.id)

    # Verify each is masked correctly
    assert masked["openai"] == "...3456"  # Last 4 of long key
    assert masked["anthropic"] == "***"  # Short key completely masked
    assert masked["azure"] == "...7890"  # Last 4 of long key
    assert masked["berget"] == "***"  # 4-char key completely masked


@pytest.mark.asyncio
async def test_get_api_credentials_masked_with_azure_extra_fields(
    tenant_repo, sample_tenant
):
    """Masking works with Azure credentials that have extra fields.

    Azure credentials include endpoint, api_version, deployment_name.
    Masking should still work correctly and only mask the api_key.
    """
    # Add Azure credential with all fields
    await tenant_repo.update_api_credential(
        tenant_id=sample_tenant.id,
        provider="azure",
        credential={
            "api_key": "azure-key-1234567890",
            "endpoint": "https://example.openai.azure.com",
            "api_version": "2024-02-15-preview",
            "deployment_name": "gpt-4",
        },
    )

    # Get masked credentials
    masked = await tenant_repo.get_api_credentials_masked(sample_tenant.id)

    # Verify only api_key is in masked result and is masked
    assert "azure" in masked
    assert masked["azure"] == "...7890"  # Last 4 of api_key
    # Note: masked dict only contains provider -> masked_key, not other fields
