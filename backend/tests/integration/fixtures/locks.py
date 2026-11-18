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


async def waits_for(
    session, racer: "asyncio.Task", racer_pid: "asyncio.Future[int]"
) -> bool:
    """Watch the racer while ``session``'s transaction stays open: True once
    the racer's backend (``racer_pid``) waits for a lock that ``session``'s
    backend holds (this pair, not any wait in the database), False once the
    racer has finished. Fails if neither happens within ten seconds."""
    holder_pid = await session.scalar(sa.text("SELECT pg_backend_pid()"))
    for _ in range(200):
        if racer.done():
            return False
        if racer_pid.done() and await session.scalar(
            sa.text("SELECT :holder = ANY(pg_blocking_pids(:racer))"),
            {"holder": holder_pid, "racer": racer_pid.result()},
        ):
            return True
        await asyncio.sleep(0.05)
    raise AssertionError(f"the racer neither finished nor waited: {racer!r}")


async def settle(*racers: "asyncio.Task") -> None:
    """Give the racers ten seconds to finish, cancel the ones still running and
    return once all have ended, so no racer's transaction outlives the test.
    Never raises a racer's error: a test calls this in ``finally`` and reports
    its own failure."""
    if racers:
        await asyncio.wait(racers, timeout=10)
    for racer in racers:
        racer.cancel()
    await asyncio.gather(*racers, return_exceptions=True)
