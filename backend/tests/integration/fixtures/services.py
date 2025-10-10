"""
Fixtures for services (mirrors src/intric/services/).

These fixtures create services with completion models.
"""
from uuid import UUID

import pytest

from intric.database.tables.service_table import Services


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
