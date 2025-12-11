"""
Fixtures for completion models (mirrors src/intric/completion_models/).

These fixtures create completion models with settings stored directly on the model.
"""
import pytest
from sqlalchemy import select

from intric.ai_models.model_enums import (
    ModelFamily,
    ModelHostingLocation,
    ModelOrg,
    ModelStability,
)
from intric.database.tables.ai_models_table import CompletionModels
from intric.database.tables.model_providers_table import ModelProviders


@pytest.fixture
def completion_model_factory(admin_user):
    """
    Factory fixture for creating completion models dynamically.

    Creates CompletionModel records for the admin user's tenant with
    settings (is_enabled, is_default) stored directly on the model.

    Usage:
        async def test_migration(completion_model_factory, db_container):
            async with db_container() as container:
                session = container.session()
                model1 = await completion_model_factory(session, "gpt-4", provider="openai")
                model2 = await completion_model_factory(session, "claude-3", provider="anthropic")

    Args:
        session: SQLAlchemy async session (required first parameter)
        name: Model name (e.g., "gpt-4", "claude-3-opus")
        nickname: Display name (defaults to name)
        provider: Provider name (defaults to "openai")
        token_limit: Max tokens (defaults to 8000)
        vision: Vision support (defaults to False)
        reasoning: Reasoning support (defaults to False)
        is_deprecated: Whether model is deprecated (defaults to False)
        is_enabled: Whether enabled for tenant (defaults to True)
        is_default: Whether default for tenant (defaults to False)
        family: Model family (defaults to provider-based)
        **kwargs: Additional model properties (hosting, stability, etc.)

    Returns:
        CompletionModels: The created database model
    """
    # Cache for providers per tenant/provider_type combo
    _provider_cache = {}

    async def _get_or_create_provider(session, tenant_id, provider_type: str):
        """Get existing provider or create a new one for this tenant/provider combo."""
        cache_key = (tenant_id, provider_type)
        if cache_key in _provider_cache:
            return _provider_cache[cache_key]

        # Check if provider already exists
        result = await session.execute(
            select(ModelProviders).where(
                ModelProviders.tenant_id == tenant_id,
                ModelProviders.provider_type == provider_type,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            _provider_cache[cache_key] = existing.id
            return existing.id

        # Create new provider
        provider = ModelProviders(
            tenant_id=tenant_id,
            name=provider_type.title(),
            provider_type=provider_type,
            credentials={"api_key": "test-key"},
            config={},
            is_active=True,
        )
        session.add(provider)
        await session.flush()

        _provider_cache[cache_key] = provider.id
        return provider.id

    async def _create_model(
        session,
        name: str,
        nickname: str = None,
        provider: str = "openai",
        token_limit: int = 8000,
        vision: bool = False,
        reasoning: bool = False,
        is_deprecated: bool = False,
        is_enabled: bool = True,
        is_default: bool = False,
        family: ModelFamily = None,
        **kwargs
    ) -> CompletionModels:
        """Create a completion model with the specified properties."""
        # Auto-determine family based on provider if not specified
        if family is None:
            family_map = {
                "openai": ModelFamily.OPEN_AI,
                "anthropic": ModelFamily.CLAUDE,
                "mistral": ModelFamily.MISTRAL,
                "azure": ModelFamily.AZURE,
            }
            family = family_map.get(provider, ModelFamily.OPEN_AI)

        # Default nickname to name if not provided
        if nickname is None:
            nickname = name

        # Determine org based on provider
        org_map = {
            "openai": ModelOrg.OPENAI,
            "anthropic": ModelOrg.ANTHROPIC,
            "meta": ModelOrg.META,
            "google": ModelOrg.GOOGLE,
        }
        org = org_map.get(provider)

        # Get or create provider for this tenant (required by check constraint)
        provider_id = await _get_or_create_provider(session, admin_user.tenant_id, provider)

        # Create the completion model with settings directly on it
        model = CompletionModels(
            tenant_id=admin_user.tenant_id,
            provider_id=provider_id,
            name=name,
            nickname=nickname,
            token_limit=token_limit,
            vision=vision,
            reasoning=reasoning,
            family=family.value,
            hosting=kwargs.get("hosting", ModelHostingLocation.USA.value),
            org=org.value if org else None,
            stability=kwargs.get("stability", ModelStability.STABLE.value),
            open_source=kwargs.get("open_source", False),
            description=kwargs.get("description"),
            nr_billion_parameters=kwargs.get("nr_billion_parameters"),
            hf_link=kwargs.get("hf_link"),
            is_deprecated=is_deprecated,
            deployment_name=kwargs.get("deployment_name"),
            base_url=kwargs.get("base_url"),
            litellm_model_name=kwargs.get("litellm_model_name"),
            # Settings are now directly on the model
            is_enabled=is_enabled,
            is_default=is_default,
            security_classification_id=kwargs.get("security_classification_id"),
        )

        session.add(model)
        await session.flush()

        return model

    return _create_model
