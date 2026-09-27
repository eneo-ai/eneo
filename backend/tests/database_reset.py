"""Row-level reset of the integration database between tests."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_LIST_TABLES = text(
    """
    SELECT tablename FROM pg_tables
    WHERE schemaname = 'public' AND tablename != 'alembic_version'
    """
)

_RESTART_SEQUENCES = text(
    """
    SELECT setval(format('%I.%I', schemaname, sequencename), start_value, false)
    FROM pg_sequences
    WHERE schemaname = 'public'
    """
)


async def reset_populated_tables(session: AsyncSession) -> list[str]:
    """Empty every public table that holds rows and restart every sequence.

    Truncating all tables rewrites every relation file and costs about half a
    second per test; deleting from the handful of populated tables costs a few
    milliseconds. Foreign-key and user triggers are disabled for the statement
    so the delete order does not matter. Unlike TRUNCATE this leaves pg_class
    statistics behind, so a test that asserts on a query plan must ANALYZE and
    measure inside its own transaction. Must run inside an open transaction.
    Returns the tables that were emptied.
    """
    tables = list((await session.execute(_LIST_TABLES)).scalars())
    probe = " UNION ALL ".join(
        f"""SELECT '{table}' WHERE EXISTS (SELECT 1 FROM "{table}")"""
        for table in tables
    )
    populated = list((await session.execute(text(probe))).scalars())
    await session.execute(text("SET LOCAL session_replication_role = replica"))
    for table in populated:
        await session.execute(text(f'DELETE FROM "{table}"'))
    await session.execute(_RESTART_SEQUENCES)
    return populated
