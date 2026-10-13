"""Work that outlives an HTTP request: Graph calls after the response is sent.

The request's database session is closed when the response goes out, so a
task scheduled from a request handler must bring its own session. The tasks
are also kept referenced until they finish; ``asyncio`` only holds a weak
reference and would otherwise let the garbage collector cancel them mid-way.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Coroutine

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.main.logging import get_logger

logger = get_logger(__name__)

_detached_tasks: set[asyncio.Task[None]] = set()


def run_detached(coro: Coroutine[object, object, None]) -> asyncio.Task[None]:
    task = asyncio.create_task(coro)
    _detached_tasks.add(task)
    task.add_done_callback(_detached_tasks.discard)
    return task


def pending_detached_tasks() -> set[asyncio.Task[None]]:
    return set(_detached_tasks)


def run_after_commit(session: object, start: Callable[[], Awaitable[None]]) -> None:
    """Start ``start()`` once ``session``'s transaction commits, never on rollback.

    A cleanup that reads what the request deleted must wait for the commit,
    or its own connection still sees the old rows. Sessions that are not real
    ``AsyncSession`` objects (tests with fakes) start immediately.
    """
    if not isinstance(session, AsyncSession):
        run_detached(_start(start))
        return

    def _on_commit(_sync_session: object) -> None:
        run_detached(_start(start))

    event.listen(session.sync_session, "after_commit", _on_commit, once=True)


async def _start(start: Callable[[], Awaitable[None]]) -> None:
    try:
        await start()
    except Exception as exc:
        logger.warning("Detached SharePoint task failed: %s", exc, exc_info=True)
