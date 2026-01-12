"""Integration tests for CompletionService error handling.

Tests that missing API key configuration returns user-friendly errors
instead of 500 Internal Server Error.

When a tenant has no API key configured (neither tenant-specific nor global),
the service should raise APIKeyNotConfiguredException with a clear error
message instead of letting ValueError propagate as a 500 error.
"""

from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import uuid4

import pytest

from intric.ai_models.completion_models.completion_model import CompletionModel
from intric.ai_models.model_enums import (
    ModelFamily,
    ModelHostingLocation,
    ModelOrg,
    ModelStability,
)
from intric.completion_models.infrastructure.completion_service import CompletionService
from intric.main.exceptions import APIKeyNotConfiguredException


@pytest.fixture
def mock_context_builder():
    """Mock ContextBuilder for testing."""
    return Mock()


@pytest.fixture
def openai_completion_model(test_tenant, admin_user):
    """OpenAI completion model."""
    return CompletionModel(
        user=admin_user,
        id=uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        nickname="gpt4",
        name="GPT-4",
        token_limit=8192,
        vision=False,
        family=ModelFamily.OPEN_AI,
        hosting=ModelHostingLocation.USA,
        org=ModelOrg.OPENAI,
        stability=ModelStability.STABLE,
        open_source=False,
        description="OpenAI GPT-4 model",
        nr_billion_parameters=None,
        hf_link=None,
        is_deprecated=False,
        deployment_name=None,
        is_org_enabled=True,
        is_org_default=False,
        reasoning=False,
        base_url=None,
        litellm_model_name=None,
    )


@pytest.fixture
def claude_completion_model(test_tenant, admin_user):
    """Claude completion model."""
    return CompletionModel(
        user=admin_user,
        id=uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        nickname="claude3",
        name="Claude 3",
        token_limit=200000,
        vision=True,
        family=ModelFamily.CLAUDE,
        hosting=ModelHostingLocation.USA,
        org=ModelOrg.ANTHROPIC,
        stability=ModelStability.STABLE,
        open_source=False,
        description="Anthropic Claude 3 Opus model",
        nr_billion_parameters=None,
        hf_link=None,
        is_deprecated=False,
        deployment_name=None,
        is_org_enabled=True,
        is_org_default=False,
        reasoning=True,
        base_url=None,
        litellm_model_name=None,
    )


@pytest.fixture
def azure_completion_model(test_tenant, admin_user):
    """Azure OpenAI completion model."""
    return CompletionModel(
        user=admin_user,
        id=uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        nickname="azure-gpt4",
        name="Azure GPT-4",
        token_limit=8192,
        vision=False,
        family=ModelFamily.AZURE,
        hosting=ModelHostingLocation.EU,
        org=ModelOrg.MICROSOFT,
        stability=ModelStability.STABLE,
        open_source=False,
        description="Azure OpenAI GPT-4 deployment",
        nr_billion_parameters=None,
        hf_link=None,
        is_deprecated=False,
        deployment_name="gpt-4",
        is_org_enabled=True,
        is_org_default=False,
        reasoning=False,
        base_url=None,
        litellm_model_name=None,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_missing_openai_api_key_returns_503(
    mock_context_builder,
    test_tenant,
    test_settings,
    openai_completion_model,
):
    """When OpenAI API key is missing, raise APIKeyNotConfiguredException with clear error message."""
    # Ensure tenant has no credentials (avoid cross-test contamination)
    tenant = test_tenant.model_copy(update={"api_credentials": {}})

    # Override settings to ensure strict mode is enabled
    settings = test_settings.model_copy(update={"tenant_credentials_enabled": True})
    assert settings.tenant_credentials_enabled is True

    service = CompletionService(
        context_builder=mock_context_builder,
        tenant=tenant,
        config=settings,
    )

    with pytest.raises(APIKeyNotConfiguredException) as exc_info:
        service._get_adapter(openai_completion_model)

    # Verify exception message
    error_message = str(exc_info.value)
    assert "No API key configured" in error_message
    assert "openai" in error_message.lower()
    # Check for either administrator guidance or credential configuration instructions
    assert (
        "administrator" in error_message.lower()
        or "configure" in error_message.lower()
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_missing_anthropic_api_key_returns_503(
    mock_context_builder,
    test_tenant,
    test_settings,
    claude_completion_model,
):
    """When Anthropic API key is missing, raise APIKeyNotConfiguredException with clear error message."""
    # Ensure tenant has no credentials
    assert test_tenant.api_credentials == {}

    # Override settings to ensure strict mode is enabled
    settings = test_settings.model_copy(update={"tenant_credentials_enabled": True})
    assert settings.tenant_credentials_enabled is True

    service = CompletionService(
        context_builder=mock_context_builder,
        tenant=test_tenant,
        config=settings,
    )

    with pytest.raises(APIKeyNotConfiguredException) as exc_info:
        service._get_adapter(claude_completion_model)

    # Verify exception message
    error_message = str(exc_info.value)
    assert "No API key configured" in error_message
    assert "anthropic" in error_message


@pytest.mark.asyncio
@pytest.mark.integration
async def test_missing_azure_api_key_returns_503(
    mock_context_builder,
    test_tenant,
    test_settings,
    azure_completion_model,
):
    """When Azure API key is missing, raise APIKeyNotConfiguredException with clear error message."""
    # Ensure tenant has no credentials
    assert test_tenant.api_credentials == {}

    # Override settings to ensure strict mode is enabled
    settings = test_settings.model_copy(update={"tenant_credentials_enabled": True})
    assert settings.tenant_credentials_enabled is True

    service = CompletionService(
        context_builder=mock_context_builder,
        tenant=test_tenant,
        config=settings,
    )

    with pytest.raises(APIKeyNotConfiguredException) as exc_info:
        service._get_adapter(azure_completion_model)

    # Verify exception message
    error_message = str(exc_info.value)
    assert "No API key configured" in error_message
    assert "azure" in error_message


@pytest.mark.asyncio
@pytest.mark.integration
async def test_error_includes_provider_context(
    mock_context_builder,
    test_tenant,
    test_settings,
    openai_completion_model,
):
    """Error message includes provider name for troubleshooting."""
    assert test_tenant.api_credentials == {}

    # Override settings to ensure strict mode is enabled
    settings = test_settings.model_copy(update={"tenant_credentials_enabled": True})
    assert settings.tenant_credentials_enabled is True

    service = CompletionService(
        context_builder=mock_context_builder,
        tenant=test_tenant,
        config=settings,
    )

    with pytest.raises(APIKeyNotConfiguredException) as exc_info:
        service._get_adapter(openai_completion_model)

    # Verify provider context is included
    error_message = str(exc_info.value)
    assert "openai" in error_message.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_error_message_is_user_friendly(
    mock_context_builder,
    test_tenant,
    test_settings,
    openai_completion_model,
):
    """Error message is clear and actionable for end users."""
    assert test_tenant.api_credentials == {}

    # Override settings to ensure strict mode is enabled
    settings = test_settings.model_copy(update={"tenant_credentials_enabled": True})
    assert settings.tenant_credentials_enabled is True

    service = CompletionService(
        context_builder=mock_context_builder,
        tenant=test_tenant,
        config=settings,
    )

    with pytest.raises(APIKeyNotConfiguredException) as exc_info:
        service._get_adapter(openai_completion_model)

    message = str(exc_info.value)

    # Verify message is user-friendly
    assert "No API key configured" in message
    assert "administrator" in message.lower() or "configure" in message.lower()
    assert "openai" in message.lower()

    # Should NOT contain technical details like stack traces
    assert "ValueError" not in message
    assert "CredentialResolver" not in message


@pytest.mark.asyncio
@pytest.mark.integration
async def test_successful_adapter_creation_with_tenant_credentials(
    db_container,
    mock_context_builder,
    test_tenant,
    test_settings,
    openai_completion_model,
):
    """When tenant has API key configured, adapter is created successfully."""
    async with db_container() as container:
        tenant_repo = container.tenant_repo()

        # Set tenant-specific OpenAI API key
        updated_tenant = await tenant_repo.update_api_credential(
            tenant_id=test_tenant.id,
            provider="openai",
            credential={"api_key": "sk-tenant-key-123"},
        )

        # Override settings to ensure strict mode is enabled
        settings = test_settings.model_copy(update={"tenant_credentials_enabled": True})
        assert settings.tenant_credentials_enabled is True

        service = CompletionService(
            context_builder=mock_context_builder,
            tenant=updated_tenant,
            config=settings,
        )

        # Should not raise any exception
        adapter = service._get_adapter(openai_completion_model)
        assert adapter is not None
