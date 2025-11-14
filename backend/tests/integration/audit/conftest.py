"""Fixtures for audit integration tests."""

import pytest
from sqlalchemy import select

from intric.database.tables.users_table import Users


@pytest.fixture
async def test_user(db_session, test_tenant):
    """Get the default test user ID."""
    async with db_session() as session:
        query = select(Users.id).where(
            Users.email == "test@example.com",
            Users.tenant_id == test_tenant.id
        )
        result = await session.execute(query)
        user_id = result.scalar_one_or_none()
        if not user_id:
            raise ValueError("No test user found in database")
        return user_id
