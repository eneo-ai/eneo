"""
Fixtures for apps (mirrors src/intric/apps/).

These fixtures create apps with completion models.
"""
from uuid import UUID

import pytest

from intric.database.tables.app_table import Apps


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
