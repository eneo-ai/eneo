"""Unit tests for CredentialResolver.

Tests tenant-specific credential resolution with strict fallback logic:
- Tenant credentials override global environment variables
- Global credentials used only when tenant has no credential for provider
- ValueError raised when neither tenant nor global credential exists
- Provider names are case-insensitive
- Logging includes proper context (tenant name, provider, source)
"""

import json
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest

from intric.main.config import Settings
from intric.settings.credential_resolver import CredentialResolver
from intric.settings.encryption_service import EncryptionService
from intric.tenants.tenant import TenantInDB

FERNET_TEST_KEY = "Goxa5kHpfhYh2lLBVmOAXoJ1i8LojRxurx8Wc1SUgL0="


def parse_json_logs(output: str) -> list[dict]:
    """Parse JSON log lines from captured stdout.

    Helper function for testing structured JSON logging output.
    Handles multi-line output with mixed JSON and non-JSON content.
    """
    logs = []
    for line in output.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        try:
            logs.append(json.loads(line))
        except json.JSONDecodeError:
            # Skip non-JSON lines (e.g., test output, print statements)
            continue
    return logs


def make_settings(**overrides):
    """Create test settings with SECURE DEFAULTS (strict mode ON).

    After fixing the multi-tenant security bug, strict mode is now the default.
    Tests that need legacy behavior must explicitly set tenant_credentials_enabled=False.
    """
    base = SimpleNamespace(
        tenant_credentials_enabled=True,  # SECURE DEFAULT: strict mode ON
        federation_per_tenant_enabled=False,
        public_origin="https://global.example.com",
        openai_api_key=None,
        anthropic_api_key=None,
        azure_api_key=None,
        berget_api_key=None,
        mistral_api_key=None,
        ovhcloud_api_key=None,
        vllm_api_key=None,
        oidc_discovery_endpoint=None,
        oidc_client_secret=None,
        oidc_client_id=None,
        oidc_tenant_id=None,
        oidc_state_ttl_seconds=600,
        oidc_redirect_grace_period_seconds=900,
        strict_oidc_redirect_validation=True,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


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


def test_legacy_mode_fallback_to_global_when_no_tenant_key(
    tenant_without_credentials, mock_settings_with_global_keys
):
    """LEGACY MODE: Global credential used when tenant has no credential for provider.

    When tenant_credentials_enabled=False (legacy/single-tenant mode), and a tenant
    does NOT have a credential for a provider, the global environment variable
    should be used as fallback.

    This test validates the legacy mode still works for backward compatibility.
    """
    # IMPORTANT: Override to legacy mode (strict mode would block this fallback)
    mock_settings_with_global_keys.tenant_credentials_enabled = False

    resolver = CredentialResolver(
        tenant_without_credentials, mock_settings_with_global_keys
    )

    # Tenant has no openai credential, should fallback to global (legacy mode)
    api_key = resolver.get_api_key("openai")
    assert api_key == "sk-global-openai-456"

    # Tenant has no anthropic credential, should fallback to global (legacy mode)
    api_key = resolver.get_api_key("anthropic")
    assert api_key == "sk-global-anthropic-789"


def test_legacy_mode_partial_tenant_credentials_with_global_fallback(
    tenant_with_credentials, mock_settings_with_global_keys
):
    """LEGACY MODE: Tenant has some credentials, falls back to global for others.

    When tenant_credentials_enabled=False (legacy mode), a tenant with partial
    credentials (has openai/anthropic but not azure) can fall back to global
    credentials for missing providers.

    This test validates legacy mode partial fallback still works.
    """
    # IMPORTANT: Override to legacy mode (strict mode would block fallback)
    mock_settings_with_global_keys.tenant_credentials_enabled = False

    resolver = CredentialResolver(tenant_with_credentials, mock_settings_with_global_keys)

    # Tenant has openai - use tenant credential
    assert resolver.get_api_key("openai") == "sk-tenant-openai-key-123"

    # Tenant doesn't have azure - use global credential (legacy mode allows this)
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
        resolver.get_credential_field("vllm", "endpoint", fallback="http://fallback", required=True)


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


def test_legacy_mode_all_six_providers_use_global(monkeypatch):
    """LEGACY MODE: All six providers work correctly with global fallback.

    When tenant_credentials_enabled=False (legacy mode), and tenant has no
    credentials configured, all six providers (openai, azure, anthropic, berget,
    mistral, ovhcloud) should fall back to global environment variables.
    """
    # Set up global credentials for all providers
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-global")
    monkeypatch.setenv("AZURE_API_KEY", "azure-global")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic-global")
    monkeypatch.setenv("BERGET_API_KEY", "berget-global")
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-global")
    monkeypatch.setenv("OVHCLOUD_API_KEY", "ovhcloud-global")
    # IMPORTANT: Disable strict mode for legacy behavior
    monkeypatch.setenv("TENANT_CREDENTIALS_ENABLED", "false")

    settings = Settings()
    tenant = TenantInDB(
        id=uuid4(),
        name="test-tenant",
        display_name="Test Tenant",
        quota_limit=1024**3,
        api_credentials={},
    )

    resolver = CredentialResolver(tenant, settings)

    # All providers should resolve to global credentials (legacy mode)
    assert resolver.get_api_key("openai") == "sk-openai-global"
    assert resolver.get_api_key("azure") == "azure-global"
    assert resolver.get_api_key("anthropic") == "sk-anthropic-global"
    assert resolver.get_api_key("berget") == "berget-global"
    assert resolver.get_api_key("mistral") == "mistral-global"
    assert resolver.get_api_key("ovhcloud") == "ovhcloud-global"


def test_all_six_providers_tenant_override(monkeypatch):
    """All six providers can be overridden at tenant level.

    Tenant-specific credentials should work for all provider types, taking
    precedence over global credentials even when both exist.
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
        display_name="Test Tenant",  # Required for Pydantic validation
        quota_limit=1024**3,
        api_credentials={
            "openai": {"api_key": "sk-openai-tenant"},
            "azure": {
                "api_key": "azure-tenant",
                "endpoint": "https://sundsvall.openai.azure.com",
                "api_version": "2024-02-15-preview",
                "deployment_name": "gpt-4-sundsvall",
            },
            "anthropic": {"api_key": "sk-anthropic-tenant"},
            "berget": {"api_key": "berget-tenant"},
            "mistral": {"api_key": "mistral-tenant"},
            "ovhcloud": {"api_key": "ovhcloud-tenant"},
        },
    )

    resolver = CredentialResolver(tenant, settings)

    # All providers should resolve to tenant credentials (precedence over global)
    assert resolver.get_api_key("openai") == "sk-openai-tenant"
    assert resolver.get_api_key("azure") == "azure-tenant"
    assert resolver.get_api_key("anthropic") == "sk-anthropic-tenant"
    assert resolver.get_api_key("berget") == "berget-tenant"
    assert resolver.get_api_key("mistral") == "mistral-tenant"
    assert resolver.get_api_key("ovhcloud") == "ovhcloud-tenant"


def test_logging_includes_tenant_context(
    caplog, tenant_with_credentials, mock_settings_with_global_keys
):
    """Logs include tenant_name, provider, credential_source for tenant credentials.

    When credentials are resolved from tenant configuration, the logs should include:
    - tenant_id
    - tenant_name
    - provider
    - credential_source = "tenant" or "global"

    NOTE: This test imports the actual SimpleLogger instance used by credential_resolver
    and attaches caplog's handler to it, since SimpleLogger instances are not registered
    with the logging manager.
    """
    # Import the actual logger instance used by credential_resolver
    from intric.settings.credential_resolver import logger as cr_logger

    # Use legacy mode to test global credential logging
    mock_settings_with_global_keys.tenant_credentials_enabled = False

    # Attach caplog's handler to the actual SimpleLogger instance
    with caplog.at_level(logging.INFO):
        cr_logger.addHandler(caplog.handler)
        try:
            resolver = CredentialResolver(
                tenant_with_credentials, mock_settings_with_global_keys
            )

            # Test tenant credential resolution (tenant has openai)
            resolver.get_api_key("openai")

            # Check log record includes expected fields
            assert any(
                "Credential resolved successfully" in r.getMessage()
                and getattr(r, "tenant_name", None) == "test-tenant"
                and getattr(r, "provider", None) == "openai"
                and getattr(r, "credential_source", None) == "tenant"
                for r in caplog.records
            ), f"Tenant credential resolution not logged correctly. Records: {[(r.getMessage(), getattr(r, 'provider', None)) for r in caplog.records]}"

            # Clear records for next test
            caplog.clear()

            # Test global credential resolution (tenant has NO azure, legacy mode allows fallback)
            resolver.get_api_key("azure")

            # Check log includes expected fields for global resolution
            assert any(
                "Credential resolved successfully" in r.getMessage()
                and getattr(r, "tenant_name", None) == "test-tenant"
                and getattr(r, "provider", None) == "azure"
                and getattr(r, "credential_source", None) == "global"
                for r in caplog.records
            ), f"Global credential resolution not logged correctly. Records: {[(r.getMessage(), getattr(r, 'provider', None)) for r in caplog.records]}"

        finally:
            cr_logger.removeHandler(caplog.handler)


def test_logging_on_error(caplog, tenant_without_credentials, mock_settings_empty):
    """Error logs include tenant_id and provider when credential not found.

    In strict mode, when tenant has no credentials, error should be logged
    with proper context before raising ValueError.

    NOTE: This test imports the actual SimpleLogger instance used by credential_resolver
    and attaches caplog's handler to it, since SimpleLogger instances are not registered
    with the logging manager.
    """
    # Import the actual logger instance used by credential_resolver
    from intric.settings.credential_resolver import logger as cr_logger

    # Attach caplog's handler to the actual SimpleLogger instance
    with caplog.at_level(logging.ERROR):
        cr_logger.addHandler(caplog.handler)
        try:
            # Strict mode is now the default (tenant_credentials_enabled=True)
            resolver = CredentialResolver(tenant_without_credentials, mock_settings_empty)

            with pytest.raises(ValueError):
                resolver.get_api_key("openai")

            # Check error log record includes context
            # Note: Error message now mentions "Tenant-specific credentials are enabled"
            assert any(
                "No credential configured for provider openai" in r.getMessage()
                and hasattr(r, "tenant_id")
                and getattr(r, "provider", None) == "openai"
                for r in caplog.records
            ), f"Error not logged with proper context. Records: {[(r.getMessage(), getattr(r, 'provider', None)) for r in caplog.records]}"

        finally:
            cr_logger.removeHandler(caplog.handler)


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
    {"api_key": "value"} format in the database. CredentialResolver should handle
    both formats for backward compatibility.

    This test uses model_construct() to bypass Pydantic validation, simulating
    legacy data that exists in the database but would be rejected by API validation.
    """
    # Use model_construct() to bypass validation (official Pydantic method)
    # This simulates legacy data already in database
    tenant = TenantInDB.model_construct(
        id=uuid4(),
        name="legacy-tenant",
        display_name="Legacy Tenant",
        quota_limit=1024**3,
        # Legacy format: string instead of {"api_key": "..."}
        # Would fail validation if using TenantInDB(...), but exists in old DB records
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
    """Settings with global OIDC config set via environment variables.

    IMPORTANT: Explicitly disables strict modes to allow legacy fallback behavior.
    """
    # Disable strict modes to allow legacy global fallback
    monkeypatch.setenv("TENANT_CREDENTIALS_ENABLED", "false")
    monkeypatch.setenv("FEDERATION_PER_TENANT_ENABLED", "false")

    # Set global OIDC configuration
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


def test_legacy_mode_fallback_to_global_oidc_when_no_tenant_federation(
    tenant_without_federation, mock_settings_with_global_oidc
):
    """LEGACY MODE: Global OIDC config used when tenant has no federation config.

    When federation_per_tenant_enabled=False (legacy mode), and a tenant does NOT
    have federation_config, the global OIDC_* environment variables should be used
    as fallback.

    This test validates legacy federation fallback still works.
    """
    # IMPORTANT: federation_per_tenant_enabled defaults to False, so this is already legacy mode
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
    a clear ValueError should be raised with helpful error message.
    """
    resolver = CredentialResolver(tenant_without_federation, mock_settings_no_oidc)

    # Updated error message pattern to match actual implementation
    with pytest.raises(
        ValueError,
        match=r"No identity provider configured"
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
    """Test that missing config raises ValueError with helpful message."""
    # Clear all OIDC env vars
    for key in ["PUBLIC_ORIGIN", "OIDC_DISCOVERY_ENDPOINT", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"]:
        monkeypatch.delenv(key, raising=False)

    settings = Settings()
    resolver = CredentialResolver(tenant=None, settings=settings)

    # Error message says "Cannot compute redirect_uri" (not "origin" specifically)
    with pytest.raises(ValueError, match="Cannot compute redirect_uri"):
        resolver.get_redirect_uri()


def test_strict_mode_blocks_cross_provider_access():
    """Tenant cannot use other provider credentials when strict mode enabled."""
    tenant_a = TenantInDB(
        id=uuid4(),
        name="Tenant A",
        quota_limit=1024**3,
        api_credentials={
            "openai": {"api_key": "tenant-a-openai"},
        },
    )

    settings = make_settings(tenant_credentials_enabled=True)
    resolver_a = CredentialResolver(tenant=tenant_a, settings=settings)

    assert resolver_a.get_api_key("openai") == "tenant-a-openai"

    with pytest.raises(ValueError, match="No API key configured for provider 'anthropic'"):
        resolver_a.get_api_key("anthropic")


def test_no_global_fallback_in_strict_mode():
    """Global env vars are ignored when tenant credentials are required."""
    settings = make_settings(
        tenant_credentials_enabled=True,
        openai_api_key="sk-global-should-not-be-used",
    )

    tenant = TenantInDB(
        id=uuid4(),
        name="Tenant",
        quota_limit=1024**3,
        api_credentials={},
    )

    resolver = CredentialResolver(tenant=tenant, settings=settings)

    with pytest.raises(ValueError, match="each tenant must configure their own credentials"):
        resolver.get_api_key("openai")


def test_plaintext_federation_secret_rejected_when_encryption_active():
    """Federation config must use encrypted client_secret when encryption is enabled."""
    tenant = TenantInDB(
        id=uuid4(),
        name="Tenant",
        quota_limit=1024**3,
        federation_config={
            "provider": "entra",
            "client_id": "client",
            "client_secret": "plaintext-secret",
            "discovery_endpoint": "https://idp.example.com/.well-known/openid-configuration",
            "canonical_public_origin": "https://tenant.example.com",
        },
    )

    settings = make_settings(federation_per_tenant_enabled=True)
    encryption = EncryptionService(FERNET_TEST_KEY)
    resolver = CredentialResolver(
        tenant=tenant,
        settings=settings,
        encryption_service=encryption,
    )

    with pytest.raises(ValueError, match="not encrypted"):
        resolver.get_federation_config()


def test_encrypted_federation_secret_decrypted_successfully():
    """Encrypted federation secrets are decrypted transparently."""
    encryption = EncryptionService(FERNET_TEST_KEY)
    encrypted_secret = encryption.encrypt("super-secret")

    tenant = TenantInDB(
        id=uuid4(),
        name="Tenant",
        quota_limit=1024**3,
        federation_config={
            "provider": "entra",
            "client_id": "client",
            "client_secret": encrypted_secret,
            "discovery_endpoint": "https://idp.example.com/.well-known/openid-configuration",
            "canonical_public_origin": "https://tenant.example.com",
        },
    )

    settings = make_settings(federation_per_tenant_enabled=True)
    resolver = CredentialResolver(
        tenant=tenant,
        settings=settings,
        encryption_service=encryption,
    )

    config = resolver.get_federation_config()
    assert config["client_secret"] == "super-secret"
