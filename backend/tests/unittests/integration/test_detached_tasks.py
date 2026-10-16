"""Post-response work starts after the commit and stays referenced until done."""

import asyncio
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.integration.infrastructure.detached_tasks import (
    pending_detached_tasks,
    run_after_commit,
)


async def _settle() -> None:
    while pending_detached_tasks():
        await asyncio.gather(*pending_detached_tasks(), return_exceptions=True)


async def test_starts_only_once_the_session_commits():
    session = AsyncSession()
    start = AsyncMock()

    run_after_commit(session, start)
    await asyncio.sleep(0)
    start.assert_not_awaited()

    await session.commit()
    await _settle()
    start.assert_awaited_once()


async def test_never_starts_when_the_session_rolls_back():
    session = AsyncSession()
    start = AsyncMock()

    run_after_commit(session, start)
    await session.rollback()
    await _settle()

    start.assert_not_awaited()


async def test_stays_referenced_until_done_and_swallows_failures():
    gate = asyncio.Event()

    async def start() -> None:
        await gate.wait()
        raise RuntimeError("boom")

    run_after_commit(object(), start)
    await asyncio.sleep(0)
    assert len(pending_detached_tasks()) == 1

    gate.set()
    await _settle()
    assert pending_detached_tasks() == set()
