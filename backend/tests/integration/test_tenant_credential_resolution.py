"""
Integration test for tenant-specific credential resolution in CompletionService.

This test verifies that CompletionService properly creates LiteLLMModelAdapter
instances with tenant-scoped CredentialResolver when accessed through the
dependency injection container.

Run with:
    cd backend && poetry run pytest tests/integration/test_tenant_credential_resolution.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from intric.completion_models.domain.completion_model import CompletionModel
from intric.completion_models.infrastructure.completion_service import CompletionService
from intric.completion_models.infrastructure.context_builder import ContextBuilder
from intric.completion_models.infrastructure.adapters.litellm_model_adapter import LiteLLMModelAdapter
from intric.ai_models.model_enums import ModelFamily, ModelHostingLocation, ModelOrg, ModelStability
from intric.tenants.tenant import TenantInDB
from intric.main.config import Settings
from intric.users.user import UserInDB


@pytest.fixture
def mock_tenant():
    """Create a mock tenant with API credentials."""
    return TenantInDB(
        id=uuid4(),
        name="Test Tenant",
        api_credentials={
            "openai": "sk-tenant-test-key",
            "anthropic": "tenant-anthropic-key"
        },
        created_at=None,
        updated_at=None
    )


@pytest.fixture
def mock_user(mock_tenant):
    """Create a mock user."""
    return UserInDB(
        id=uuid4(),
        email="test@example.com",
        tenant_id=mock_tenant.id,
        hashed_password="hashed",
        is_active=True,
        is_admin=False,
        created_at=None,
        updated_at=None
    )


@pytest.fixture
def mock_settings():
    """Create mock settings with global API keys."""
    return Settings(
        openai_api_key="sk-global-test-key",
        anthropic_api_key="global-anthropic-key"
    )


@pytest.fixture
def litellm_completion_model(mock_user):
    """Create a CompletionModel configured to use LiteLLM."""
    return CompletionModel(
        user=mock_user,
        id=uuid4(),
        created_at=None,
        updated_at=None,
        nickname="Test GPT-4",
        name="gpt-4",
        token_limit=8192,
        vision=False,
        family=ModelFamily.OPEN_AI,
        hosting=ModelHostingLocation.HOSTED,
        org=ModelOrg.OPENAI,
        stability=ModelStability.STABLE,
        open_source=False,
        description="Test model",
        nr_billion_parameters=None,
        hf_link=None,
        is_deprecated=False,
        deployment_name=None,
        is_org_enabled=True,
        is_org_default=False,
        reasoning=False,
        litellm_model_name="openai/gpt-4",  # LiteLLM model name triggers adapter selection
        security_classification=None
    )


@pytest.mark.asyncio
async def test_completion_service_creates_adapter_with_tenant_credentials(
    mock_tenant,
    mock_settings,
    litellm_completion_model
):
    """
    Verify CompletionService creates LiteLLMModelAdapter with tenant-scoped CredentialResolver.
    """
    # Arrange
    context_builder = ContextBuilder()
    completion_service = CompletionService(
        context_builder=context_builder,
        tenant=mock_tenant,
        config=mock_settings
    )

    # Act
    adapter = completion_service._get_adapter(litellm_completion_model)

    # Assert
    assert isinstance(adapter, LiteLLMModelAdapter), "Should create LiteLLMModelAdapter for litellm_model_name"
    assert adapter.credential_resolver is not None, "Adapter should have credential_resolver"
    assert adapter.credential_resolver.tenant == mock_tenant, "Credential resolver should have tenant context"
    assert adapter.credential_resolver.settings == mock_settings, "Credential resolver should have settings"


@pytest.mark.asyncio
async def test_completion_service_without_tenant_creates_adapter_without_credentials(
    mock_settings,
    litellm_completion_model
):
    """
    Verify CompletionService creates LiteLLMModelAdapter without CredentialResolver when tenant is None.

    This ensures backward compatibility for cases where tenant context is not available.
    """
    # Arrange
    context_builder = ContextBuilder()
    completion_service = CompletionService(
        context_builder=context_builder,
        tenant=None,  # No tenant context
        config=mock_settings
    )

    # Act
    adapter = completion_service._get_adapter(litellm_completion_model)

    # Assert
    assert isinstance(adapter, LiteLLMModelAdapter), "Should create LiteLLMModelAdapter for litellm_model_name"
    assert adapter.credential_resolver is None, "Adapter should not have credential_resolver when tenant is None"


@pytest.mark.asyncio
async def test_completion_service_uses_tenant_api_key_in_request(
    mock_tenant,
    mock_settings,
    litellm_completion_model
):
    """
    Verify that tenant-specific API key is injected into LiteLLM requests.
    """
    # Arrange
    context_builder = ContextBuilder()
    completion_service = CompletionService(
        context_builder=context_builder,
        tenant=mock_tenant,
        config=mock_settings
    )

    # Create mock context
    mock_context = MagicMock()
    mock_context.prompt = "Test prompt"
    mock_context.messages = []
    mock_context.input = "Test input"
    mock_context.images = []

    # Mock litellm.acompletion
    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Test response"))]
        mock_acompletion.return_value = mock_response

        # Act
        adapter = completion_service._get_adapter(litellm_completion_model)
        await adapter.get_response(context=mock_context, model_kwargs=None)

        # Assert
        mock_acompletion.assert_called_once()
        call_kwargs = mock_acompletion.call_args.kwargs

        # Verify tenant API key was injected
        assert "api_key" in call_kwargs, "API key should be injected into request"
        assert call_kwargs["api_key"] == "sk-tenant-test-key", "Should use tenant-specific API key"


@pytest.mark.asyncio
async def test_completion_service_falls_back_to_global_key_when_no_tenant_credential(
    mock_settings,
    litellm_completion_model
):
    """
    Verify that global API key is used when tenant has no specific credential.
    """
    # Arrange
    tenant_without_openai = TenantInDB(
        id=uuid4(),
        name="Tenant Without OpenAI Key",
        api_credentials={
            "anthropic": "tenant-anthropic-key"  # Has Anthropic but not OpenAI
        },
        created_at=None,
        updated_at=None
    )

    context_builder = ContextBuilder()
    completion_service = CompletionService(
        context_builder=context_builder,
        tenant=tenant_without_openai,
        config=mock_settings
    )

    # Create mock context
    mock_context = MagicMock()
    mock_context.prompt = "Test prompt"
    mock_context.messages = []
    mock_context.input = "Test input"
    mock_context.images = []

    # Mock litellm.acompletion
    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Test response"))]
        mock_acompletion.return_value = mock_response

        # Act
        adapter = completion_service._get_adapter(litellm_completion_model)
        await adapter.get_response(context=mock_context, model_kwargs=None)

        # Assert
        mock_acompletion.assert_called_once()
        call_kwargs = mock_acompletion.call_args.kwargs

        # Verify global API key was used as fallback
        assert "api_key" in call_kwargs, "API key should be injected into request"
        assert call_kwargs["api_key"] == "sk-global-test-key", "Should fall back to global API key"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
