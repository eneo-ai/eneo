"""Apply retention wait limits to runner transactions and health reads."""

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
