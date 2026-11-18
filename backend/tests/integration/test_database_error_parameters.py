"""A database error does not list the statement's bound values.

The unhandled-error handler logs the exception text and traceback, so the
values SQLAlchemy appends to an error (a session id, a key hash, an email)
would reach the logs.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


async def test_a_failing_statement_does_not_list_its_bound_values(test_settings):
    from eneo.database import database

    manager = database.DatabaseSessionManager()
    manager.init(test_settings.database_url)
    secret = "sid-that-must-not-be-logged"
    try:
        async with manager.connect() as connection:
            # The server's own message ("division by zero") names no value.
            with pytest.raises(DBAPIError) as raised:
                await connection.execute(
                    text("SELECT CAST(:value AS text), 1 / 0"), {"value": secret}
                )
        assert secret not in str(raised.value)
    finally:
        await manager.close()
