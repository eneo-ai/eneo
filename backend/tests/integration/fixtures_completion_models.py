"""
Shared fixtures for completion models across all integration tests.

These fixtures are automatically available to all tests through pytest's
fixture discovery mechanism when imported in conftest.py.
"""
from typing import Any, Dict, List
from uuid import UUID

import pytest

from intric.ai_models.model_enums import (
    ModelFamily,
    ModelHostingLocation,
    ModelOrg,
    ModelStability,
)
from intric.database.tables.ai_models_table import (
    CompletionModels,
    CompletionModelSettings,
)
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.app_table import Apps
from intric.database.tables.service_table import Services
from intric.database.tables.spaces_table import Spaces, SpacesCompletionModels


@pytest.fixture
def completion_model_factory(admin_user):
    """
    Factory fixture for creating completion models dynamically.

    Creates both the CompletionModel record and its associated settings
    for the admin user's tenant. This fixture is shared across all integration
    tests and can be used anywhere completion models are needed.

    IMPORTANT: This factory requires a session to be passed in. Use it within
    a db_container context.

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
        is_org_enabled: Whether enabled for tenant (defaults to True)
        is_org_default: Whether default for tenant (defaults to False)
        family: Model family (defaults to provider-based)
        **kwargs: Additional model properties (hosting, stability, etc.)

    Returns:
        CompletionModels: The created database model
    """
    async def _create_model(
        session,
        name: str,
        nickname: str = None,
        provider: str = "openai",
        token_limit: int = 8000,
        vision: bool = False,
        reasoning: bool = False,
        is_deprecated: bool = False,
        is_org_enabled: bool = True,
        is_org_default: bool = False,
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

        # Create the completion model
        model = CompletionModels(
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
        )

        session.add(model)
        await session.flush()

        # Create settings for the admin user's tenant
        settings = CompletionModelSettings(
            completion_model_id=model.id,
            tenant_id=admin_user.tenant_id,
            is_org_enabled=is_org_enabled,
            is_org_default=is_org_default,
        )

        session.add(settings)
        await session.flush()

        return model

    return _create_model


@pytest.fixture
def assistant_factory(admin_user):
    """
    Factory fixture for creating assistants with specific completion models.

    This allows you to quickly create test assistants with any model,
    custom parameters, and settings.

    Usage:
        async def test_assistant_migration(assistant_factory, completion_model_factory, db_container):
            async with db_container() as container:
                session = container.session()
                model = await completion_model_factory(session, "gpt-4")
                assistant = await assistant_factory(session, "My Assistant", model.id)
                # With custom kwargs
                assistant2 = await assistant_factory(
                    session, "Custom Assistant", model.id,
                    kwargs={"temperature": 0.7}
                )

    Args:
        session: SQLAlchemy async session (required first parameter)
        name: Assistant name
        completion_model_id: UUID of the completion model to use
        kwargs: Model kwargs (optional, defaults to {})
        **extra: Additional assistant properties (logging_enabled, published, etc.)

    Returns:
        Assistants: The created assistant
    """
    async def _create_assistant(
        session,
        name: str,
        completion_model_id: UUID,
        kwargs: Dict[str, Any] = None,
        **extra
    ) -> Assistants:
        """Create an assistant with the specified model."""
        if kwargs is None:
            kwargs = {}

        # Set defaults for optional boolean fields
        defaults = {
            "logging_enabled": True,
            "is_default": False,
            "published": False,
        }
        defaults.update(extra)

        assistant = Assistants(
            name=name,
            user_id=admin_user.id,
            completion_model_id=completion_model_id,
            completion_model_kwargs=kwargs,
            **defaults
        )

        session.add(assistant)
        await session.flush()

        return assistant

    return _create_assistant


@pytest.fixture
def app_factory(admin_user, space_factory):
    """
    Factory fixture for creating apps with specific completion models.

    Usage:
        async def test_app_migration(app_factory, completion_model_factory, db_container):
            async with db_container() as container:
                session = container.session()
                model = await completion_model_factory(session, "gpt-4")
                app = await app_factory(session, "My App", model.id)

    Args:
        session: SQLAlchemy async session (required first parameter)
        name: App name
        completion_model_id: UUID of the completion model to use
        space_id: Optional space ID (will create default space if not provided)
        **extra: Additional app properties

    Returns:
        Apps: The created app
    """
    async def _create_app(
        session,
        name: str,
        completion_model_id: UUID,
        space_id: UUID = None,
        **extra
    ) -> Apps:
        """Create an app with the specified model."""
        # Create a default space if not provided (Apps require a space)
        if space_id is None:
            space = await space_factory(session, f"Space for {name}")
            space_id = space.id

        # Set defaults for required fields
        defaults = {
            "published": False,
        }
        defaults.update(extra)

        app = Apps(
            name=name,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            space_id=space_id,
            completion_model_id=completion_model_id,
            **defaults
        )

        session.add(app)
        await session.flush()

        return app

    return _create_app


@pytest.fixture
def service_factory(admin_user):
    """
    Factory fixture for creating services with specific completion models.

    Usage:
        async def test_service_migration(service_factory, completion_model_factory, db_container):
            async with db_container() as container:
                session = container.session()
                model = await completion_model_factory(session, "gpt-4")
                service = await service_factory(session, "My Service", model.id)

    Args:
        session: SQLAlchemy async session (required first parameter)
        name: Service name
        completion_model_id: UUID of the completion model to use
        prompt: Optional service prompt (defaults to a generic prompt)
        **extra: Additional service properties

    Returns:
        Services: The created service
    """
    async def _create_service(
        session,
        name: str,
        completion_model_id: UUID,
        prompt: str = None,
        **extra
    ) -> Services:
        """Create a service with the specified model."""
        # Use a default prompt if not provided (required field)
        if prompt is None:
            prompt = f"Service prompt for {name}"

        service = Services(
            name=name,
            prompt=prompt,
            user_id=admin_user.id,
            completion_model_id=completion_model_id,
            **extra
        )

        session.add(service)
        await session.flush()

        return service

    return _create_service


@pytest.fixture
def space_factory(admin_user):
    """
    Factory fixture for creating spaces with access to specific completion models.

    Usage:
        async def test_space_migration(space_factory, completion_model_factory, db_container):
            async with db_container() as container:
                session = container.session()
                model1 = await completion_model_factory(session, "gpt-4")
                model2 = await completion_model_factory(session, "claude-3")
                space = await space_factory(session, "My Space", [model1.id, model2.id])

    Args:
        session: SQLAlchemy async session (required first parameter)
        name: Space name
        model_ids: List of completion model IDs to enable for this space
        **extra: Additional space properties

    Returns:
        Spaces: The created space
    """
    async def _create_space(
        session,
        name: str,
        model_ids: List[UUID] = None,
        **extra
    ) -> Spaces:
        """Create a space with access to the specified models."""
        if model_ids is None:
            model_ids = []

        space = Spaces(
            name=name,
            tenant_id=admin_user.tenant_id,
            **extra
        )

        session.add(space)
        await session.flush()

        # Add model associations
        for model_id in model_ids:
            association = SpacesCompletionModels(
                space_id=space.id,
                completion_model_id=model_id,
            )
            session.add(association)

        await session.flush()

        return space

    return _create_space
