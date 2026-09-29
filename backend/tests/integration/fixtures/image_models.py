"""
Fixtures for image models (mirrors src/eneo/image_models/).

Parallel to the transcription_model_factory, used by the image model
lifecycle and built-in provider integration tests.
"""

import pytest
from sqlalchemy import select

from eneo.database.tables.ai_models_table import ImageModels
from eneo.database.tables.model_providers_table import ModelProviders


@pytest.fixture
def image_model_factory(admin_user):
    """Factory for creating tenant image models.

    Usage:
        async with db_container() as container:
            session = container.session()
            model = await image_model_factory(session, "gpt-image-1")
    """
    _provider_cache = {}

    async def _get_or_create_provider(session, tenant_id, provider_type: str):
        cache_key = (tenant_id, provider_type)
        if cache_key in _provider_cache:
            return _provider_cache[cache_key]

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
        is_deprecated: bool = False,
        is_enabled: bool = True,
        is_default: bool = False,
        default_size: str = "auto",
        default_quality: str = "auto",
        **kwargs,
    ) -> ImageModels:
        if nickname is None:
            nickname = name

        provider_id = await _get_or_create_provider(
            session, admin_user.tenant_id, provider
        )

        model = ImageModels(
            tenant_id=admin_user.tenant_id,
            provider_id=provider_id,
            name=name,
            nickname=nickname,
            family=kwargs.get("family", "openai"),
            hosting=kwargs.get("hosting", "usa"),
            org=kwargs.get("org"),
            stability=kwargs.get("stability", "stable"),
            open_source=kwargs.get("open_source", False),
            description=kwargs.get("description"),
            hf_link=kwargs.get("hf_link"),
            cost_per_image=kwargs.get("cost_per_image"),
            default_size=default_size,
            default_quality=default_quality,
            is_deprecated=is_deprecated,
            is_enabled=is_enabled,
            is_default=is_default,
            security_classification_id=kwargs.get("security_classification_id"),
        )
        session.add(model)
        await session.flush()
        return model

    return _create_model
