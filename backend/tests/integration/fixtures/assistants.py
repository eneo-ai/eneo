"""
Fixtures for assistants (mirrors src/intric/assistants/).

These fixtures create assistants with completion models.
"""
from typing import Any, Dict
from uuid import UUID

import pytest

from intric.database.tables.assistant_table import Assistants


@pytest.fixture
def assistant_factory(admin_user):
    """
    Factory fixture for creating assistants with specific completion models.

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
