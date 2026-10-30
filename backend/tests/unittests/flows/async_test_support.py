from __future__ import annotations

import asyncio
from typing import Any


async def until_task_reaches(point: asyncio.Event, task: asyncio.Task[Any]) -> None:
    """Wait until ``task`` sets ``point``.

    A task that ends before it reaches the point fails the test at once
    instead of hanging the run, so a defect that ends the code under test
    early is reported as a failure.
    """
    waiting = asyncio.ensure_future(point.wait())
    await asyncio.wait({task, waiting}, return_when=asyncio.FIRST_COMPLETED)
    waiting.cancel()
    assert point.is_set(), "the task ended before it reached the awaited point"
