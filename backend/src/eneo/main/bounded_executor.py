"""Run blocking work on a few threads without building an executor backlog."""

import asyncio
import contextvars
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import ParamSpec, TypeVar

_P = ParamSpec("_P")
_T = TypeVar("_T")


class BoundedExecutor:
    """Callers wait for a free worker on the event loop, never in the executor's
    queue, so a caller cancelled while waiting leaves nothing behind. The work
    runs in a copy of the caller's context, as with ``asyncio.to_thread``."""

    def __init__(self, max_workers: int, thread_name_prefix: str) -> None:
        self._max_workers = max_workers
        self._executor = ThreadPoolExecutor(max_workers, thread_name_prefix)
        self._slots: asyncio.Semaphore | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def run(
        self, function: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs
    ) -> _T:
        loop = asyncio.get_running_loop()
        if self._slots is None or self._loop is not loop:
            self._slots = asyncio.Semaphore(self._max_workers)
            self._loop = loop
        slots = self._slots
        await slots.acquire()
        try:
            future = loop.run_in_executor(
                self._executor,
                contextvars.copy_context().run,
                partial(function, *args, **kwargs),
            )
        except BaseException:
            slots.release()
            raise

        # Cancelling an await cannot stop a thread. Keep its slot until actual
        # completion so repeated cancellation cannot build an executor backlog.
        def completed(result: asyncio.Future[_T]) -> None:
            slots.release()
            if not result.cancelled():
                result.exception()  # Retrieve failures even when the caller was cancelled.

        future.add_done_callback(completed)
        return await asyncio.shield(future)
