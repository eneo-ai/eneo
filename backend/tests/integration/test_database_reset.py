"""The per-test database reset must leave no rows and restart every sequence."""

import pytest
from sqlalchemy import text

from eneo.database.database import sessionmanager
from tests.database_reset import reset_populated_tables


@pytest.mark.integration
async def test_reset_empties_populated_tables_and_restarts_sequences():
    async with sessionmanager.session() as session, session.begin():
        sequence = (
            await session.execute(
                text(
                    """
                    SELECT format('%I.%I', schemaname, sequencename), start_value
                    FROM pg_sequences WHERE schemaname = 'public'
                    ORDER BY 1 LIMIT 1
                    """
                )
            )
        ).first()
        if sequence is not None:
            name, start_value = sequence
            await session.execute(text(f"SELECT nextval('{name}'), nextval('{name}')"))

        # The baseline seed populates tenants and users, joined by a foreign key.
        emptied = await reset_populated_tables(session)

        assert {"tenants", "users"} <= set(emptied)
        assert await reset_populated_tables(session) == []
        if sequence is not None:
            assert (
                await session.scalar(text(f"SELECT nextval('{name}')")) == start_value
            )
