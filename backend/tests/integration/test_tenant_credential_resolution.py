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

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from intric.completion_models.domain.completion_model import CompletionModel
from intric.completion_models.infrastructure.completion_service import CompletionService
from intric.completion_models.infrastructure.context_builder import ContextBuilder
from intric.completion_models.infrastructure.adapters.litellm_model_adapter import LiteLLMModelAdapter
from intric.ai_models.model_enums import ModelFamily, ModelHostingLocation, ModelOrg, ModelStability
from intric.tenants.tenant import TenantInDB
from intric.tenants.tenant_repo import TenantRepository
from intric.main.config import Settings
from intric.settings.encryption_service import EncryptionService
from intric.users.user import UserInDB, UserState


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


@pytest.fixture
def mock_tenant():
    """Create a mock tenant with API credentials."""
    return TenantInDB(
        id=uuid4(),
        name="Test Tenant",
        quota_limit=10 * 1024**3,  # 10 GB default
        api_credentials={
            "openai": {"api_key": "sk-tenant-test-key"},
            "anthropic": {"api_key": "tenant-anthropic-key"}
        },
        created_at=None,
        updated_at=None
    )


@pytest.fixture
def mock_user(mock_tenant):
    """Create a mock user."""
    from intric.users.user import UserState
    return UserInDB(
        id=uuid4(),
        email="test@example.com",
        tenant_id=mock_tenant.id,
        tenant=mock_tenant,
        hashed_password="hashed",
        is_active=True,
        is_admin=False,
        state=UserState.ACTIVE,
        created_at=None,
        updated_at=None
    )


@pytest.fixture
def mock_settings():
    """Create mock settings with global API keys in legacy mode."""
    return Settings(
        openai_api_key="sk-global-test-key",
        anthropic_api_key="global-anthropic-key",
        tenant_credentials_enabled=False  # Legacy mode: use global credentials
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
        hosting=ModelHostingLocation.USA,
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
@pytest.mark.integration
async def test_completion_service_creates_adapter_with_tenant_credentials(
    legacy_credentials_mode,
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
@pytest.mark.integration
async def test_completion_service_without_tenant_creates_adapter_without_credentials(
    legacy_credentials_mode,
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
@pytest.mark.integration
async def test_completion_service_uses_tenant_api_key_in_request(
    client: AsyncClient,
    async_session: AsyncSession,
    test_tenant,
    super_admin_token: str,
    encryption_service: EncryptionService,
    test_settings,
):
    """
    Verify that tenant-specific API key is injected into LiteLLM requests.

    This integration test:
    1. Stores encrypted credentials via API
    2. Retrieves tenant with credentials from database
    3. Creates CompletionService with real tenant in strict mode
    4. Verifies decrypted API key is injected into LiteLLM calls
    """
    # Step 1: Store tenant-specific OpenAI credential via API
    tenant_id = str(test_tenant.id)
    test_api_key = "sk-tenant-test-key-xyz789"

    await _put_tenant_credential(
        client,
        super_admin_token,
        tenant_id,
        "openai",
        {"api_key": test_api_key}
    )

    # Step 2: Retrieve tenant from database (credentials are encrypted)
    repo = TenantRepository(async_session)
    tenant = await repo.get(test_tenant.id)
    assert tenant is not None
    assert "openai" in tenant.api_credentials

    # Step 3: Create CompletionModel for testing
    test_user = UserInDB(
        id=uuid4(),
        email="test@example.com",
        tenant_id=tenant.id,
        tenant=tenant,
        hashed_password="hashed",
        is_active=True,
        is_admin=False,
        state=UserState.ACTIVE,
        created_at=None,
        updated_at=None
    )

    completion_model = CompletionModel(
        user=test_user,
        id=uuid4(),
        created_at=None,
        updated_at=None,
        nickname="Test GPT-4",
        name="gpt-4",
        token_limit=8192,
        vision=False,
        family=ModelFamily.OPEN_AI,
        hosting=ModelHostingLocation.USA,
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
        litellm_model_name="openai/gpt-4",
        security_classification=None
    )

    # Step 4: Create CompletionService with real tenant (strict mode)
    context_builder = ContextBuilder()
    completion_service = CompletionService(
        context_builder=context_builder,
        tenant=tenant,
        config=test_settings,  # This has tenant_credentials_enabled=True (strict mode)
        encryption_service=encryption_service  # Required for decrypting credentials
    )

    # Step 5: Create mock context
    mock_context = MagicMock()
    mock_context.prompt = "Test prompt"
    mock_context.messages = []
    mock_context.input = "Test input"
    mock_context.images = []

    # Step 6: Mock litellm.acompletion and verify API key injection
    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Test response"))]
        mock_acompletion.return_value = mock_response

        # Act: Get adapter and make request
        adapter = completion_service._get_adapter(completion_model)
        await adapter.get_response(context=mock_context, model_kwargs=None)

        # Assert: Verify tenant API key was decrypted and injected
        mock_acompletion.assert_called_once()
        call_kwargs = mock_acompletion.call_args.kwargs

        assert "api_key" in call_kwargs, "API key should be injected into request"
        assert call_kwargs["api_key"] == test_api_key, (
            f"Should use tenant-specific decrypted API key. "
            f"Expected: {test_api_key}, Got: {call_kwargs.get('api_key')}"
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_completion_service_falls_back_to_global_key_when_no_tenant_credential(
    legacy_credentials_mode,
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
        quota_limit=10 * 1024**3,  # 10 GB default
        api_credentials={
            "anthropic": {"api_key": "tenant-anthropic-key"}  # Has Anthropic but not OpenAI
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
