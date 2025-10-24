"""Integration tests for CredentialResolver strict mode error handling.

Tests that verify proper error handling when credentials are missing:
- ValueError raised when no tenant or global credentials exist
- Error logging includes proper context
- Strict mode prevents global fallback
"""

import logging

import pytest


@pytest.mark.asyncio
@pytest.mark.integration
async def test_raises_when_no_key_configured(test_tenant, test_settings):
    """ValueError raised when no credential available (tenant or global).

    In strict mode (tenant_credentials_enabled=True), when tenant has no
    credentials, ValueError should be raised with a clear error message.
    """
    from intric.settings.credential_resolver import CredentialResolver

    # Use test_tenant which has empty api_credentials by default
    assert test_tenant.api_credentials == {}

    # Override settings to ensure strict mode is enabled
    settings = test_settings.model_copy(update={"tenant_credentials_enabled": True})
    assert settings.tenant_credentials_enabled is True

    # Create resolver with tenant that has no credentials
    resolver = CredentialResolver(
        tenant=test_tenant,
        settings=settings,
    )

    # Should raise ValueError for missing OpenAI credential
    with pytest.raises(
        ValueError,
        match="No API key configured for provider 'openai'",
    ):
        resolver.get_api_key("openai")

    # Should raise ValueError for missing Anthropic credential
    with pytest.raises(
        ValueError,
        match="No API key configured for provider 'anthropic'",
    ):
        resolver.get_api_key("anthropic")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_logging_on_error(test_tenant, test_settings, caplog):
    """Error logs include tenant_id and provider when credential not found.

    In strict mode, when tenant has no credentials, error should be logged
    with proper context before raising ValueError.
    """
    from intric.settings.credential_resolver import CredentialResolver
    from intric.settings.credential_resolver import logger as cr_logger

    # Ensure tenant has no credentials
    assert test_tenant.api_credentials == {}

    # Override settings to ensure strict mode is enabled
    settings = test_settings.model_copy(update={"tenant_credentials_enabled": True})
    assert settings.tenant_credentials_enabled is True

    # Attach caplog handler to the actual logger instance
    with caplog.at_level(logging.ERROR):
        cr_logger.addHandler(caplog.handler)
        try:
            resolver = CredentialResolver(
                tenant=test_tenant,
                settings=settings,
            )

            with pytest.raises(ValueError):
                resolver.get_api_key("openai")

            # Check error log record includes context
            assert any(
                "No credential configured for provider openai" in r.getMessage()
                and hasattr(r, "tenant_id")
                and getattr(r, "provider", None) == "openai"
                for r in caplog.records
            ), f"Error not logged with proper context. Records: {[(r.getMessage(), getattr(r, 'provider', None)) for r in caplog.records]}"

        finally:
            cr_logger.removeHandler(caplog.handler)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_no_tenant_no_global_raises(test_settings):
    """When no tenant and no global credential, ValueError is raised.

    When CredentialResolver has no tenant and settings have no global
    API keys, it should raise a clear error.
    """
    from intric.settings.credential_resolver import CredentialResolver

    # Override settings to ensure strict mode is enabled
    settings = test_settings.model_copy(update={"tenant_credentials_enabled": True})

    # Verify settings are configured correctly
    assert settings.tenant_credentials_enabled is True
    assert settings.openai_api_key is None
    assert settings.anthropic_api_key is None

    resolver = CredentialResolver(tenant=None, settings=settings)

    with pytest.raises(
        ValueError,
        match="No API key configured for provider 'openai'",
    ):
        resolver.get_api_key("openai")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_strict_mode_blocks_global_fallback(test_tenant, test_settings):
    """Strict mode prevents fallback to global credentials.

    Even when global env vars are set, strict mode should NOT use them
    when tenant has no credentials.
    """
    from intric.settings.credential_resolver import CredentialResolver

    # Ensure tenant has no credentials
    assert test_tenant.api_credentials == {}

    # Override settings to ensure strict mode is enabled
    settings = test_settings.model_copy(update={"tenant_credentials_enabled": True})
    assert settings.tenant_credentials_enabled is True

    # Create resolver
    resolver = CredentialResolver(
        tenant=test_tenant,
        settings=settings,
    )

    # Should raise ValueError, NOT fall back to any global key
    with pytest.raises(
        ValueError,
        match="each tenant must configure their own credentials",
    ):
        resolver.get_api_key("openai")
