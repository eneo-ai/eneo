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
        """Create a space with access to the specified models.

        Creates a child space (with tenant_space_id set to org space) to avoid
        UNIQUE CONSTRAINT violations on org spaces.
        """
        from sqlalchemy import select

        if model_ids is None:
            model_ids = []

        # Get or create org space for this tenant
        from intric.database.tables.spaces_table import Spaces as SpacesTable

        org_space = (
            await session.execute(
                select(SpacesTable).where(
                    (SpacesTable.tenant_id == admin_user.tenant_id) &
                    (SpacesTable.user_id.is_(None)) &
                    (SpacesTable.tenant_space_id.is_(None))
                )
            )
        ).scalar_one_or_none()

        if org_space is None:
            # Create org space if it doesn't exist
            org_space = Spaces(
                name=f"Org Space for {admin_user.tenant_id}",
                tenant_id=admin_user.tenant_id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space)
            await session.flush()

        # Create child space under org space
        space = Spaces(
            name=name,
            tenant_id=admin_user.tenant_id,
            tenant_space_id=org_space.id,  # Make it a child space
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
