"""
Fixtures for spaces (mirrors src/intric/spaces/).

These fixtures create spaces with access to completion models.
"""
from typing import List
from uuid import UUID

import pytest

from intric.database.tables.spaces_table import Spaces, SpacesCompletionModels


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
