"""Unit tests for CredentialResolver.

Tests tenant-specific credential resolution with strict fallback logic:
- Tenant credentials override global environment variables
- Global credentials used only when tenant has no credential for provider
- ValueError raised when neither tenant nor global credential exists
- Provider names are case-insensitive
- Logging includes proper context (tenant name, provider, source)
"""

import logging
from uuid import uuid4

import pytest

from intric.main.config import Settings
from intric.settings.credential_resolver import CredentialResolver
from intric.tenants.tenant import TenantInDB


@pytest.fixture
def tenant_with_credentials():
    """Tenant with API credentials configured."""
    return TenantInDB(
        id=uuid4(),
        name="test-tenant",
        display_name="Test Tenant",
        quota_limit=1024**3,
        api_credentials={
            "openai": {"api_key": "sk-tenant-openai-key-123"},
            "anthropic": {"api_key": "sk-tenant-anthropic-key-456"},
        },
    )


@pytest.fixture
def tenant_without_credentials():
    """Tenant with no API credentials."""
    return TenantInDB(
        id=uuid4(),
        name="empty-tenant",
        display_name="Empty Tenant",
        quota_limit=1024**3,
        api_credentials={},
    )


@pytest.fixture
def mock_settings_with_global_keys(monkeypatch):
    """Settings with global API keys set via environment variables."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-global-openai-456")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-global-anthropic-789")
    monkeypatch.setenv("AZURE_API_KEY", "azure-global-key-111")
    monkeypatch.setenv("BERGET_API_KEY", "berget-global-key-222")
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-global-key-333")
    monkeypatch.setenv("OVHCLOUD_API_KEY", "ovhcloud-global-key-444")
    return Settings()


@pytest.fixture
def mock_settings_empty(monkeypatch):
    """Settings with no global API keys."""
    # Clear all API key environment variables
    for key in [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AZURE_API_KEY",
        "BERGET_API_KEY",
        "MISTRAL_API_KEY",
        "OVHCLOUD_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)
    return Settings()


def test_tenant_credential_overrides_global(
    tenant_with_credentials, mock_settings_with_global_keys
):
    """Tenant credential takes precedence over global environment variable.

    When a tenant has a credential for a provider, it should be used
    exclusively, even if a global credential exists.
    """
    resolver = CredentialResolver(tenant_with_credentials, mock_settings_with_global_keys)

    # Tenant has openai credential, should use tenant's not global
    api_key = resolver.get_api_key("openai")
    assert api_key == "sk-tenant-openai-key-123"

    # Tenant has anthropic credential, should use tenant's not global
    api_key = resolver.get_api_key("anthropic")
    assert api_key == "sk-tenant-anthropic-key-456"


def test_fallback_to_global_when_no_tenant_key(
    tenant_without_credentials, mock_settings_with_global_keys
):
    """Global credential used when tenant has no credential for provider.

    When a tenant does NOT have a credential for a provider, the global
    environment variable should be used as fallback.
    """
    resolver = CredentialResolver(
        tenant_without_credentials, mock_settings_with_global_keys
    )

    # Tenant has no openai credential, should fallback to global
    api_key = resolver.get_api_key("openai")
    assert api_key == "sk-global-openai-456"

    # Tenant has no anthropic credential, should fallback to global
    api_key = resolver.get_api_key("anthropic")
    assert api_key == "sk-global-anthropic-789"


def test_partial_tenant_credentials_with_global_fallback(
    tenant_with_credentials, mock_settings_with_global_keys
):
    """Tenant has some credentials, falls back to global for others.

    Tenant has openai and anthropic configured, but not azure.
    Should use tenant credentials for openai/anthropic, global for azure.
    """
    resolver = CredentialResolver(tenant_with_credentials, mock_settings_with_global_keys)

    # Tenant has openai - use tenant credential
    assert resolver.get_api_key("openai") == "sk-tenant-openai-key-123"

    # Tenant doesn't have azure - use global credential
    assert resolver.get_api_key("azure") == "azure-global-key-111"


def test_raises_when_no_key_configured(tenant_without_credentials, mock_settings_empty):
    """ValueError raised when no credential available (tenant or global).

    When neither the tenant nor global environment has a credential,
    a clear ValueError should be raised.
    """
    resolver = CredentialResolver(tenant_without_credentials, mock_settings_empty)

    with pytest.raises(ValueError, match="No API key configured for provider 'openai'"):
        resolver.get_api_key("openai")

    with pytest.raises(
        ValueError, match="No API key configured for provider 'anthropic'"
    ):
        resolver.get_api_key("anthropic")


def test_raises_when_tenant_has_no_key_and_no_global(
    tenant_with_credentials, mock_settings_empty
):
    """ValueError raised when tenant lacks credential and no global exists.

    Tenant has openai and anthropic, but not azure. Global also has no azure.
    Should raise ValueError for azure.
    """
    resolver = CredentialResolver(tenant_with_credentials, mock_settings_empty)

    # Tenant has openai - works
    assert resolver.get_api_key("openai") == "sk-tenant-openai-key-123"

    # Tenant doesn't have azure, global doesn't either - should raise
    with pytest.raises(ValueError, match="No API key configured for provider 'azure'"):
        resolver.get_api_key("azure")


def test_case_insensitive_provider_names(
    tenant_with_credentials, mock_settings_with_global_keys
):
    """Provider names are normalized to lowercase.

    Credentials are stored in lowercase. API should accept mixed case.
    """
    resolver = CredentialResolver(tenant_with_credentials, mock_settings_with_global_keys)

    # Test various case combinations
    assert resolver.get_api_key("OpenAI") == "sk-tenant-openai-key-123"
    assert resolver.get_api_key("OPENAI") == "sk-tenant-openai-key-123"
    assert resolver.get_api_key("openai") == "sk-tenant-openai-key-123"
    assert resolver.get_api_key("Anthropic") == "sk-tenant-anthropic-key-456"
    assert resolver.get_api_key("ANTHROPIC") == "sk-tenant-anthropic-key-456"


def test_missing_required_field_for_tenant_raises():
    """Tenant credential missing required field should raise ValueError."""

    tenant = TenantInDB(
        id=uuid4(),
        name="tenant-missing-endpoint",
        quota_limit=1024**3,
        api_credentials={
            "vllm": {
                "api_key": "tenant-vllm-key",
                # endpoint intentionally omitted to simulate misconfiguration
            }
        },
    )

    settings = Settings(
        tenant_credentials_enabled=True,
        vllm_model_url="http://global-vllm",
    )

    resolver = CredentialResolver(tenant, settings)

    match_text = "missing required field 'endpoint'"
    with pytest.raises(ValueError, match=match_text):
        resolver.get_credential_field("vllm", "endpoint", fallback="http://fallback")


def test_missing_field_in_single_tenant_mode_uses_fallback():
    """When strict mode disabled, missing field falls back to global value."""

    tenant = TenantInDB(
        id=uuid4(),
        name="single-tenant",
        quota_limit=1024**3,
        api_credentials={},
    )

    fallback_endpoint = "http://shared-vllm"
    settings = Settings(
        tenant_credentials_enabled=False,
        vllm_model_url=fallback_endpoint,
    )

    resolver = CredentialResolver(tenant, settings)

    endpoint = resolver.get_credential_field("vllm", "endpoint", fallback=fallback_endpoint)
    assert endpoint == fallback_endpoint


def test_all_six_providers(monkeypatch):
    """All six providers work correctly (openai, azure, anthropic, berget, mistral, ovhcloud).

    Each provider should be resolvable using the same logic.
    """
    # Set up global credentials for all providers
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-global")
    monkeypatch.setenv("AZURE_API_KEY", "azure-global")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic-global")
    monkeypatch.setenv("BERGET_API_KEY", "berget-global")
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-global")
    monkeypatch.setenv("OVHCLOUD_API_KEY", "ovhcloud-global")

    settings = Settings()
    tenant = TenantInDB(
        id=uuid4(),
        name="test-tenant",
        quota_limit=1024**3,
        api_credentials={},
    )

    resolver = CredentialResolver(tenant, settings)

    # All providers should resolve to global credentials
    assert resolver.get_api_key("openai") == "sk-openai-global"
    assert resolver.get_api_key("azure") == "azure-global"
    assert resolver.get_api_key("anthropic") == "sk-anthropic-global"
    assert resolver.get_api_key("berget") == "berget-global"
    assert resolver.get_api_key("mistral") == "mistral-global"
    assert resolver.get_api_key("ovhcloud") == "ovhcloud-global"


def test_all_six_providers_tenant_override(monkeypatch):
    """All six providers can be overridden at tenant level.

    Tenant-specific credentials should work for all provider types.
    """
    # Set up global credentials
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-global")
    monkeypatch.setenv("AZURE_API_KEY", "azure-global")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic-global")
    monkeypatch.setenv("BERGET_API_KEY", "berget-global")
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-global")
    monkeypatch.setenv("OVHCLOUD_API_KEY", "ovhcloud-global")

    settings = Settings()
    tenant = TenantInDB(
        id=uuid4(),
        name="test-tenant",
        quota_limit=1024**3,
        api_credentials={
            "openai": {"api_key": "sk-openai-tenant"},
            "azure": {"api_key": "azure-tenant"},
            "anthropic": {"api_key": "sk-anthropic-tenant"},
            "berget": {"api_key": "berget-tenant"},
            "mistral": {"api_key": "mistral-tenant"},
            "ovhcloud": {"api_key": "ovhcloud-tenant"},
        },
    )

    resolver = CredentialResolver(tenant, settings)

    # All providers should resolve to tenant credentials
    assert resolver.get_api_key("openai") == "sk-openai-tenant"
    assert resolver.get_api_key("azure") == "azure-tenant"
    assert resolver.get_api_key("anthropic") == "sk-anthropic-tenant"
    assert resolver.get_api_key("berget") == "berget-tenant"
    assert resolver.get_api_key("mistral") == "mistral-tenant"
    assert resolver.get_api_key("ovhcloud") == "ovhcloud-tenant"


def test_logging_includes_tenant_context(
    tenant_with_credentials, mock_settings_with_global_keys, caplog
):
    """Logs include tenant_name, provider, credential_source.

    When credentials are resolved, the logs should include:
    - tenant_id
    - tenant_name
    - provider
    - credential_source (tenant or global)
    """
    with caplog.at_level(logging.INFO):
        resolver = CredentialResolver(
            tenant_with_credentials, mock_settings_with_global_keys
        )

        # Test tenant credential resolution
        resolver.get_api_key("openai")

        # Check log includes expected fields
        assert any(
            "Credential resolved successfully" in record.message
            and record.tenant_name == "test-tenant"
            and record.provider == "openai"
            and record.credential_source == "tenant"
            for record in caplog.records
        ), "Tenant credential resolution not logged correctly"

        # Clear logs
        caplog.clear()

        # Test global credential resolution
        resolver.get_api_key("azure")

        # Check log includes expected fields for global resolution
        assert any(
            "Credential resolved successfully" in record.message
            and record.tenant_name == "test-tenant"
            and record.provider == "azure"
            and record.credential_source == "global"
            for record in caplog.records
        ), "Global credential resolution not logged correctly"


def test_logging_on_error(tenant_without_credentials, mock_settings_empty, caplog):
    """Error logs include tenant_id and provider when credential not found."""
    with caplog.at_level(logging.ERROR):
        resolver = CredentialResolver(tenant_without_credentials, mock_settings_empty)

        with pytest.raises(ValueError):
            resolver.get_api_key("openai")

        # Check error log includes context
        assert any(
            "No credential configured for provider openai" in record.message
            and hasattr(record, "tenant_id")
            and record.provider == "openai"
            for record in caplog.records
        ), "Error not logged with proper context"


def test_no_tenant_uses_global(mock_settings_with_global_keys):
    """When no tenant provided, only global credentials are used.

    CredentialResolver should work without a tenant (e.g., system-level operations).
    """
    resolver = CredentialResolver(tenant=None, settings=mock_settings_with_global_keys)

    # Should use global credentials
    assert resolver.get_api_key("openai") == "sk-global-openai-456"
    assert resolver.get_api_key("anthropic") == "sk-global-anthropic-789"


def test_no_tenant_no_global_raises(mock_settings_empty):
    """When no tenant and no global credential, ValueError is raised."""
    resolver = CredentialResolver(tenant=None, settings=mock_settings_empty)

    with pytest.raises(ValueError, match="No API key configured for provider 'openai'"):
        resolver.get_api_key("openai")


def test_legacy_string_format_credentials():
    """Support legacy string format for credentials (not just dict with api_key).

    Some tenants might have credentials stored as plain strings instead of
    {"api_key": "value"} format. Should handle both.
    """
    tenant = TenantInDB(
        id=uuid4(),
        name="legacy-tenant",
        quota_limit=1024**3,
        # Note: This would fail validation in TenantInDB.validate_api_credentials
        # This test documents expected behavior if validation is bypassed
        api_credentials={"openai": "sk-legacy-string-key"},
    )

    settings = Settings()
    resolver = CredentialResolver(tenant, settings)

    # The code checks isinstance(tenant_cred, str) and uses it directly
    api_key = resolver.get_api_key("openai")
    assert api_key == "sk-legacy-string-key"
