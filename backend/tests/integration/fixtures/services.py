"""
Fixtures for services (mirrors src/eneo/services/).

These fixtures create services with completion models.
"""

from uuid import UUID

import pytest

from eneo.database.tables.service_table import Services

# Sentinel so the fixture can distinguish "caller omitted kwargs" (→ `{}`)
# from "caller passed explicit None" (→ SQL NULL). A plain `None` default
# would collapse those two cases together and quietly break tests that
# need to plant a NULL row on purpose.
_KWARGS_UNSET: object = object()


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
        kwargs: completion_model_kwargs JSONB value. Omit to default to {};
            pass explicit None to insert SQL NULL.
        **extra: Additional service properties

    Returns:
        Services: The created service
    """

    async def _create_service(
        session,
        name: str,
        completion_model_id: UUID,
        prompt: str = None,
        kwargs=_KWARGS_UNSET,
        **extra,
    ) -> Services:
        """Create a service with the specified model."""
        # Use a default prompt if not provided (required field)
        if prompt is None:
            prompt = f"Service prompt for {name}"

        if kwargs is _KWARGS_UNSET:
            kwargs = {}
        # else: pass through unchanged — including explicit None (→ SQL NULL).

        service = Services(
            name=name,
            prompt=prompt,
            user_id=admin_user.id,
            completion_model_id=completion_model_id,
            completion_model_kwargs=kwargs,
            **extra,
        )

        session.add(service)
        await session.flush()

        return service

    return _create_service
