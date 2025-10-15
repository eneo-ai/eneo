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


# ============================================================================
# Federation Config Tests
# ============================================================================


@pytest.fixture
def tenant_with_federation():
    """Tenant with federation config configured."""
    return TenantInDB(
        id=uuid4(),
        name="federated-tenant",
        display_name="Federated Tenant",
        quota_limit=1024**3,
        federation_config={
            "provider": "entra-id",
            "discovery_endpoint": "https://login.microsoftonline.com/tenant123/.well-known/openid-configuration",
            "client_id": "app-client-id-456",
            "client_secret": "encrypted-client-secret-789",
            "allowed_domains": ["example.com"],
        },
    )


@pytest.fixture
def tenant_without_federation():
    """Tenant with no federation config."""
    return TenantInDB(
        id=uuid4(),
        name="non-federated-tenant",
        display_name="Non-Federated Tenant",
        quota_limit=1024**3,
        federation_config={},
    )


@pytest.fixture
def mock_settings_with_global_oidc(monkeypatch):
    """Settings with global OIDC config set via environment variables."""
    monkeypatch.setenv("OIDC_DISCOVERY_ENDPOINT", "https://oidc.global.com/.well-known/openid-configuration")
    monkeypatch.setenv("OIDC_CLIENT_ID", "global-client-id")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "global-client-secret")
    monkeypatch.setenv("OIDC_TENANT_ID", "global-tenant-123")
    return Settings()


@pytest.fixture
def mock_settings_no_oidc(monkeypatch):
    """Settings with no global OIDC config."""
    for key in ["OIDC_DISCOVERY_ENDPOINT", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_TENANT_ID"]:
        monkeypatch.delenv(key, raising=False)
    return Settings()


@pytest.fixture
def mock_settings_federation_enabled(monkeypatch):
    """Settings with federation per tenant enabled."""
    monkeypatch.setenv("FEDERATION_PER_TENANT_ENABLED", "true")
    # Must also set encryption key to avoid validation error
    monkeypatch.setenv("ENCRYPTION_KEY", "test-encryption-key-32-chars-long!!")
    return Settings()


def test_tenant_federation_config_resolved(tenant_with_federation, mock_settings_with_global_oidc):
    """Tenant federation config takes precedence over global OIDC config.

    When a tenant has federation_config, it should be used exclusively,
    even if global OIDC_* environment variables exist.
    """
    resolver = CredentialResolver(tenant_with_federation, mock_settings_with_global_oidc)

    config = resolver.get_federation_config()

    assert config["provider"] == "entra-id"
    assert config["discovery_endpoint"] == "https://login.microsoftonline.com/tenant123/.well-known/openid-configuration"
    assert config["client_id"] == "app-client-id-456"
    assert config["client_secret"] == "encrypted-client-secret-789"
    assert config["allowed_domains"] == ["example.com"]


def test_fallback_to_global_oidc_when_no_tenant_federation(
    tenant_without_federation, mock_settings_with_global_oidc
):
    """Global OIDC config used when tenant has no federation config.

    When a tenant does NOT have federation_config, the global OIDC_*
    environment variables should be used as fallback.
    """
    resolver = CredentialResolver(tenant_without_federation, mock_settings_with_global_oidc)

    config = resolver.get_federation_config()

    assert config["provider"] == "mobilityguard"  # Legacy global provider
    assert config["discovery_endpoint"] == "https://oidc.global.com/.well-known/openid-configuration"
    assert config["client_id"] == "global-client-id"
    assert config["client_secret"] == "global-client-secret"
    assert config["tenant_id"] == "global-tenant-123"
    assert config["scopes"] == ["openid", "email", "profile"]


def test_strict_mode_raises_when_no_tenant_federation(
    tenant_without_federation, mock_settings_federation_enabled
):
    """Strict mode: ValueError when tenant has no federation config.

    When FEDERATION_PER_TENANT_ENABLED=true and tenant has no federation_config,
    should raise ValueError (no fallback to global OIDC).
    """
    resolver = CredentialResolver(tenant_without_federation, mock_settings_federation_enabled)

    with pytest.raises(
        ValueError,
        match=r"No identity provider configured for tenant 'non-federated-tenant'.*Federation per tenant is enabled"
    ):
        resolver.get_federation_config()


def test_raises_when_no_federation_anywhere(tenant_without_federation, mock_settings_no_oidc):
    """ValueError raised when no federation config available (tenant or global).

    When neither the tenant nor global environment has federation config,
    a clear ValueError should be raised.
    """
    resolver = CredentialResolver(tenant_without_federation, mock_settings_no_oidc)

    with pytest.raises(
        ValueError,
        match=r"No identity provider configured.*Please set global OIDC_\* environment variables"
    ):
        resolver.get_federation_config()


def test_no_tenant_uses_global_oidc(mock_settings_with_global_oidc):
    """When no tenant provided, only global OIDC config is used.

    CredentialResolver should work without a tenant (e.g., system-level operations).
    """
    resolver = CredentialResolver(tenant=None, settings=mock_settings_with_global_oidc)

    config = resolver.get_federation_config()

    assert config["provider"] == "mobilityguard"
    assert config["discovery_endpoint"] == "https://oidc.global.com/.well-known/openid-configuration"
    assert config["client_id"] == "global-client-id"
    assert config["client_secret"] == "global-client-secret"


def test_no_tenant_no_global_oidc_raises(mock_settings_no_oidc):
    """When no tenant and no global OIDC config, ValueError is raised."""
    resolver = CredentialResolver(tenant=None, settings=mock_settings_no_oidc)

    with pytest.raises(
        ValueError,
        match=r"No identity provider configured"
    ):
        resolver.get_federation_config()


# ============================================================================
# Redirect URI Tests
# ============================================================================


def test_get_redirect_uri_single_tenant_with_proxy_url(monkeypatch):
    """Test single-tenant with proxy URL (Sundsvall case)."""
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://m00-https-eneo-test.login.sundsvall.se")
    monkeypatch.setenv("OIDC_DISCOVERY_ENDPOINT", "https://example.com/.well-known/openid-configuration")
    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-secret")

    settings = Settings()
    resolver = CredentialResolver(tenant=None, settings=settings)

    redirect_uri = resolver.get_redirect_uri()

    assert redirect_uri == "https://m00-https-eneo-test.login.sundsvall.se/login/callback"


def test_get_redirect_uri_multi_tenant_with_clean_url(monkeypatch):
    """Test multi-tenant with clean URL (Stockholm case)."""
    monkeypatch.setenv("OIDC_DISCOVERY_ENDPOINT", "https://example.com/.well-known/openid-configuration")
    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-secret")

    settings = Settings()
    tenant = TenantInDB(
        id=uuid4(),
        name="Stockholm",
        quota_limit=1024**3,
        federation_config={
            "provider": "entra_id",
            "client_id": "stockholm-client",
            "client_secret": "secret",
            "discovery_endpoint": "https://login.microsoftonline.com/.well-known/openid-configuration",
            "canonical_public_origin": "https://stockholm.eneo.se",
        },
    )
    resolver = CredentialResolver(tenant=tenant, settings=settings)

    redirect_uri = resolver.get_redirect_uri()

    assert redirect_uri == "https://stockholm.eneo.se/login/callback"


def test_get_redirect_uri_custom_path(monkeypatch):
    """Test custom redirect_path per tenant."""
    monkeypatch.setenv("OIDC_DISCOVERY_ENDPOINT", "https://example.com/.well-known/openid-configuration")
    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-secret")

    settings = Settings()
    tenant = TenantInDB(
        id=uuid4(),
        name="Custom",
        quota_limit=1024**3,
        federation_config={
            "provider": "okta",
            "client_id": "client",
            "client_secret": "secret",
            "discovery_endpoint": "https://okta.com/.well-known/openid-configuration",
            "canonical_public_origin": "https://custom.eneo.se",
            "redirect_path": "/auth/callback",
        },
    )
    resolver = CredentialResolver(tenant=tenant, settings=settings)

    redirect_uri = resolver.get_redirect_uri()

    assert redirect_uri == "https://custom.eneo.se/auth/callback"


def test_get_redirect_uri_no_config_raises(monkeypatch):
    """Test that missing config raises ValueError."""
    # Clear all OIDC env vars
    for key in ["PUBLIC_ORIGIN", "OIDC_DISCOVERY_ENDPOINT", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"]:
        monkeypatch.delenv(key, raising=False)

    settings = Settings()
    resolver = CredentialResolver(tenant=None, settings=settings)

    with pytest.raises(ValueError, match="No public origin configured"):
        resolver.get_redirect_uri()
