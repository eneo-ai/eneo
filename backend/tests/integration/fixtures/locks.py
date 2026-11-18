import asyncio

import sqlalchemy as sa


async def wait_until_blocked(session, racer: "asyncio.Task") -> None:
    """Return once the racer waits for a row lock held by ``session``'s
    transaction, so that transaction is released only after the racer has
    lined up behind it. (The racer's query text is not visible here: asyncpg
    reports the statement it is blocked in as the transaction's BEGIN.)"""
    for _ in range(200):
        if racer.done():
            raise AssertionError(
                f"racer finished before the lock was released: {racer.exception()!r}"
            )
        # pg_stat_activity is a per-transaction snapshot: without clearing
        # it a racer that connected after the first poll is never seen.
        await session.execute(sa.text("SELECT pg_stat_clear_snapshot()"))
        blocked = await session.scalar(
            sa.text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE datname = current_database()"
                " AND pid <> pg_backend_pid()"
                " AND wait_event_type = 'Lock'"
            )
        )
        if blocked:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"the racer never waited for the lock: {racer!r}")
