"""Keep crawler parsing and chunking responsive with at most two submitted jobs."""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import ParamSpec, TypeVar

_P = ParamSpec("_P")
_T = TypeVar("_T")
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="crawler-cpu")
_slots: asyncio.Semaphore | None = None
_loop: asyncio.AbstractEventLoop | None = None


async def run_cpu_work(
    function: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs
) -> _T:
    global _slots, _loop
    loop = asyncio.get_running_loop()
    if _slots is None or _loop is not loop:
        _slots = asyncio.Semaphore(2)
        _loop = loop
    slots = _slots
    await slots.acquire()
    try:
        future = loop.run_in_executor(_executor, partial(function, *args, **kwargs))
    except BaseException:
        slots.release()
        raise

    # Cancelling an await cannot stop a thread. Keep its slot until actual
    # completion so repeated cancellation cannot build an executor backlog.
    def completed(result: asyncio.Future[_T]) -> None:
        slots.release()
        if not result.cancelled():
            result.exception()  # Retrieve failures even when the awaiting crawl was cancelled.

    future.add_done_callback(completed)
    return await asyncio.shield(future)
