"""
Fixtures for organization-based knowledge tests.

These fixtures support testing knowledge distribution across org space and child spaces.
"""
from uuid import uuid4

import pytest

from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users
from intric.database.tables.integration_table import (
    Integration,
    TenantIntegration,
    UserIntegration,
)
from intric.database.tables.ai_models_table import EmbeddingModels


@pytest.fixture
def tenant_factory(admin_user):
    """
    Factory fixture for creating tenants.

    Usage:
        async def test_something(tenant_factory, db_container):
            async with db_container() as container:
                session = container.session()
                tenant = await tenant_factory(session, name="My Tenant")

    Args:
        session: SQLAlchemy async session
        name: Tenant name (defaults to generated name)
        quota_limit: Quota limit (defaults to 1000000)
        **extra: Additional tenant properties

    Returns:
        Tenants: The created tenant
    """
    async def _create_tenant(session, name: str = None, quota_limit: int = None, **extra) -> Tenants:
        """Create a tenant."""
        if name is None:
            name = f"Tenant-{str(uuid4())[:8]}"

        if quota_limit is None:
            quota_limit = 1000000  # Default quota limit

        tenant = Tenants(name=name, state="active", quota_limit=quota_limit, **extra)
        session.add(tenant)
        await session.flush()
        return tenant

    return _create_tenant


@pytest.fixture
def user_factory(admin_user):
    """
    Factory fixture for creating users.

    Usage:
        async def test_something(user_factory, tenant_factory, db_container):
            async with db_container() as container:
                session = container.session()
                tenant = await tenant_factory(session)
                user = await user_factory(session, tenant_id=tenant.id)

    Args:
        session: SQLAlchemy async session
        tenant_id: Tenant ID (defaults to admin_user's tenant)
        email: User email (defaults to generated)
        username: Username (defaults to email)
        **extra: Additional user properties

    Returns:
        Users: The created user
    """
    async def _create_user(
        session,
        tenant_id=None,
        email: str = None,
        username: str = None,
        **extra
    ) -> Users:
        """Create a user."""
        if tenant_id is None:
            tenant_id = admin_user.tenant_id

        if email is None:
            email = f"user-{str(uuid4())[:8]}@example.com"

        if username is None:
            username = email.split("@")[0]

        user = Users(
            username=username,
            email=email,
            tenant_id=tenant_id,
            password="hashed_password",
            salt="salt",
            state="active",
            **extra
        )
        session.add(user)
        await session.flush()
        # SpaceActor expects user_groups_ids (domain property not on DB model)
        if not hasattr(user, "user_groups_ids"):
            user.user_groups_ids = set()
        return user

    return _create_user


@pytest.fixture
def user_integration_factory(admin_user):
    """
    Factory fixture for creating user integrations (authenticated integrations).

    Usage:
        async def test_something(user_integration_factory, db_container):
            async with db_container() as container:
                session = container.session()
                user_integration = await user_integration_factory(session, tenant_id=...)

    Args:
        session: SQLAlchemy async session
        tenant_id: Tenant ID (defaults to admin_user's tenant)
        **extra: Additional properties

    Returns:
        UserIntegration: The created user integration with proper tenant_integration
    """
    async def _create_user_integration(
        session,
        tenant_id=None,
        integration_name: str = None,
        **extra
    ) -> UserIntegration:
        """Create a user integration."""
        if tenant_id is None:
            tenant_id = admin_user.tenant_id

        if integration_name is None:
            integration_name = f"test-integration-{str(uuid4())[:8]}"

        # First create Integration if it doesn't exist
        integration = Integration(
            name=integration_name,
            description=f"{integration_name} test integration",
            integration_type="test",
        )
        session.add(integration)
        await session.flush()

        # Then create TenantIntegration
        tenant_integration = TenantIntegration(
            tenant_id=tenant_id,
            integration_id=integration.id,
        )
        session.add(tenant_integration)
        await session.flush()

        # Finally create UserIntegration
        user_integration = UserIntegration(
            user_id=admin_user.id,
            tenant_id=tenant_id,
            tenant_integration_id=tenant_integration.id,
            authenticated=True,
            **extra
        )
        session.add(user_integration)
        await session.flush()
        return user_integration

    return _create_user_integration


@pytest.fixture
def embedding_model_factory(admin_user):
    """
    Factory fixture for creating embedding models.

    Usage:
        async def test_something(embedding_model_factory, db_container):
            async with db_container() as container:
                session = container.session()
                model = await embedding_model_factory(session)

    Args:
        session: SQLAlchemy async session
        name: Model name
        provider: Provider name
        **extra: Additional properties

    Returns:
        EmbeddingModels: The created embedding model
    """
    async def _create_embedding_model(
        session,
        name: str = None,
        **extra
    ) -> EmbeddingModels:
        """Create an embedding model."""
        if name is None:
            name = f"embedding-model-{str(uuid4())[:8]}"

        model = EmbeddingModels(
            name=name,
            open_source=False,
            family="test-family",
            stability="stable",
            hosting="cloud",
            description=f"{name} embedding model",
            **extra
        )
        session.add(model)
        await session.flush()
        return model

    return _create_embedding_model
