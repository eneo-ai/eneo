"""Integration tests for CompletionService error handling.

Tests that missing API key configuration returns user-friendly errors
instead of 500 Internal Server Error.

When a tenant has no API key configured (provider has empty/invalid credentials),
the service should raise APIKeyNotConfiguredException with a clear error
message instead of letting errors propagate as 500 errors.

NOTE: With the new provider-based architecture, all models must have a provider_id.
APIKeyNotConfiguredException is raised when:
1. The provider exists but has empty/invalid credentials
2. The actual API call fails due to missing credentials
"""

from datetime import datetime, timezone
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
from intric.database.tables.model_providers_table import ModelProviders
from intric.main.exceptions import ProviderInactiveException, ProviderNotFoundException


@pytest.fixture
async def provider_without_credentials(db_container, test_tenant):
    """Create a provider with empty credentials for testing missing API key scenarios."""
    async with db_container() as container:
        session = container.session()

        provider = ModelProviders(
            tenant_id=test_tenant.id,
            name="OpenAI (No Credentials)",
            provider_type="openai",
            credentials={},  # Empty credentials - will cause APIKeyNotConfiguredException
            config={},
            is_active=True,
        )
        session.add(provider)
        await session.flush()

        yield provider


@pytest.fixture
async def provider_with_credentials(db_container, test_tenant):
    """Create a provider with valid credentials."""
    async with db_container() as container:
        session = container.session()

        provider = ModelProviders(
            tenant_id=test_tenant.id,
            name="OpenAI (With Credentials)",
            provider_type="openai",
            credentials={"api_key": "sk-test-key-123"},
            config={},
            is_active=True,
        )
        session.add(provider)
        await session.flush()

        yield provider


@pytest.mark.integration
@pytest.mark.asyncio
async def test_model_without_provider_id_raises_value_error(
    db_container,
    test_tenant,
    test_settings,
    admin_user,
):
    """When a model has no provider_id, raise ValueError with clear message."""
    from unittest.mock import Mock

    # Create model WITHOUT provider_id (invalid in new architecture)
    model = CompletionModel(
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
        # provider_id is NOT set
    )

    async with db_container() as container:
        service = CompletionService(
            context_builder=Mock(),
            tenant=test_tenant,
            config=test_settings,
            session=container.session(),
        )

        with pytest.raises(ValueError) as exc_info:
            await service._get_adapter(model)

        assert "missing required provider_id" in str(exc_info.value)
        assert "GPT-4" in str(exc_info.value)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_model_with_inactive_provider_raises_error(
    db_container,
    test_tenant,
    test_settings,
    admin_user,
):
    """When a model's provider is inactive, raise ProviderInactiveException."""
    from unittest.mock import Mock

    async with db_container() as container:
        session = container.session()

        # Create inactive provider
        provider = ModelProviders(
            tenant_id=test_tenant.id,
            name="Inactive Provider",
            provider_type="openai",
            credentials={"api_key": "sk-test"},
            config={},
            is_active=False,  # Inactive!
        )
        session.add(provider)
        await session.flush()

        # Create model with the inactive provider
        model = CompletionModel(
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
            provider_id=provider.id,
        )

        service = CompletionService(
            context_builder=Mock(),
            tenant=test_tenant,
            config=test_settings,
            session=session,
        )

        with pytest.raises(ProviderInactiveException) as exc_info:
            await service._get_adapter(model)

        assert "inactive" in str(exc_info.value).lower()
        assert "Inactive Provider" in str(exc_info.value)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_model_with_nonexistent_provider_raises_error(
    db_container,
    test_tenant,
    test_settings,
    admin_user,
):
    """When a model's provider doesn't exist, raise ProviderNotFoundException."""
    from unittest.mock import Mock

    async with db_container() as container:
        session = container.session()

        # Create model with a non-existent provider ID
        non_existent_provider_id = uuid4()
        model = CompletionModel(
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
            provider_id=non_existent_provider_id,
        )

        service = CompletionService(
            context_builder=Mock(),
            tenant=test_tenant,
            config=test_settings,
            session=session,
        )

        with pytest.raises(ProviderNotFoundException) as exc_info:
            await service._get_adapter(model)

        assert "not found" in str(exc_info.value).lower()
        assert str(non_existent_provider_id) in str(exc_info.value)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_adapter_creation_succeeds_with_valid_provider(
    db_container,
    test_tenant,
    test_settings,
    admin_user,
):
    """When provider exists and is active, adapter is created successfully."""
    from unittest.mock import Mock

    async with db_container() as container:
        session = container.session()

        # Create active provider with credentials (unique name to avoid conflicts)
        provider = ModelProviders(
            tenant_id=test_tenant.id,
            name="OpenAI Test Provider",
            provider_type="openai",
            credentials={"api_key": "sk-test-key-123"},
            config={},
            is_active=True,
        )
        session.add(provider)
        await session.flush()

        # Create model with the provider
        model = CompletionModel(
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
            provider_id=provider.id,
        )

        service = CompletionService(
            context_builder=Mock(),
            tenant=test_tenant,
            config=test_settings,
            session=session,
        )

        # Should not raise any exception
        adapter = await service._get_adapter(model)
        assert adapter is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_different_provider_types_create_correct_adapters(
    db_container,
    test_tenant,
    test_settings,
    admin_user,
):
    """Test that different provider types (openai, anthropic, azure) create correct adapters."""
    from unittest.mock import Mock

    provider_configs = [
        ("openai", ModelFamily.OPEN_AI, ModelOrg.OPENAI),
        ("anthropic", ModelFamily.CLAUDE, ModelOrg.ANTHROPIC),
        ("azure", ModelFamily.AZURE, ModelOrg.MICROSOFT),
    ]

    async with db_container() as container:
        session = container.session()

        for provider_type, family, org in provider_configs:
            # Create provider
            provider = ModelProviders(
                tenant_id=test_tenant.id,
                name=f"{provider_type.title()} Provider",
                provider_type=provider_type,
                credentials={"api_key": f"sk-{provider_type}-test"},
                config={},
                is_active=True,
            )
            session.add(provider)
            await session.flush()

            # Create model
            model = CompletionModel(
                user=admin_user,
                id=uuid4(),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                nickname=f"{provider_type}-model",
                name=f"{provider_type.title()} Model",
                token_limit=8192,
                vision=False,
                family=family,
                hosting=ModelHostingLocation.USA,
                org=org,
                stability=ModelStability.STABLE,
                open_source=False,
                description=f"{provider_type.title()} model",
                nr_billion_parameters=None,
                hf_link=None,
                is_deprecated=False,
                deployment_name="gpt-4" if provider_type == "azure" else None,
                is_org_enabled=True,
                is_org_default=False,
                reasoning=False,
                base_url=None,
                litellm_model_name=None,
                provider_id=provider.id,
            )

            service = CompletionService(
                context_builder=Mock(),
                tenant=test_tenant,
                config=test_settings,
                session=session,
            )

            adapter = await service._get_adapter(model)
            assert adapter is not None, f"Failed to create adapter for {provider_type}"
