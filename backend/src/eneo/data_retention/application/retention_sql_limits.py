"""Apply retention wait limits to runner transactions and explicit requests."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


async def set_retention_timeouts(
    session: AsyncSession, *, statement_timeout_ms: int, lock_timeout_ms: int
) -> None:
    await session.execute(
        sa.select(
            sa.func.set_config("statement_timeout", f"{statement_timeout_ms}ms", True),
            sa.func.set_config("lock_timeout", f"{lock_timeout_ms}ms", True),
        )
    )


@asynccontextmanager
async def retention_request_sql_limits(
    session: AsyncSession, *, statement_timeout_ms: int, lock_timeout_ms: int
) -> AsyncGenerator[None]:
    """Roll back a refused request unit without poisoning its caller's transaction.

    PostgreSQL restores LOCAL settings on savepoint rollback; successful requests
    restore them explicitly so later work uses the caller's original limits.
    """
    async with session.begin_nested():
        previous_lock, previous_statement = (
            await session.execute(
                sa.select(
                    sa.cast(sa.func.current_setting("lock_timeout"), sa.String),
                    sa.cast(sa.func.current_setting("statement_timeout"), sa.String),
                )
            )
        ).one()
        await set_retention_timeouts(
            session,
            statement_timeout_ms=statement_timeout_ms,
            lock_timeout_ms=lock_timeout_ms,
        )
        yield
        await session.execute(
            sa.select(
                sa.func.set_config("lock_timeout", previous_lock, True),
                sa.func.set_config("statement_timeout", previous_statement, True),
            )
        )
