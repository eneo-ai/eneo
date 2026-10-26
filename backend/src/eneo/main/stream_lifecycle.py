"""Deterministic release of a streamed turn's resources.

A streamed answer is a chain of async generators: the provider stream, the
model/tool loop, the completion service's typed chunks, the assistant's
accumulator and the SSE body. ``async for`` never closes the generator it
reads, so every link closes its source (``contextlib.aclosing`` or
``closing``), and the response closes the body on the task that iterated it.

Two rules make the ``finally`` blocks along that chain reliable:

- Cleanup runs inside ``finalizing(...)``: a shielded cancel scope with one
  deadline shared by every link in the task, so a disconnect that lands
  mid-await cannot cut the cleanup short and a hung close cannot hold the
  request open.
- A generator that never started cannot run its ``finally``. Where resources
  are acquired before the first iteration, ``OwnedAsyncGenerator`` runs the
  owner's release instead.

Cancel scopes may only be entered here, on the task doing the cleanup, after
no task-bound scope (an MCP connection's) remains on it; the connection host
in ``mcp_client`` keeps those on a task of their own.
"""

from __future__ import annotations

from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    Awaitable,
    Callable,
    Generator,
)
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from types import TracebackType
from typing import TypeVar

import anyio

from eneo.main.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# One budget for releasing everything a turn holds (pending approvals, MCP
# connections, the provider stream), not one per link.
FINALIZATION_BUDGET_SECONDS = 10.0

_finalization_deadline: ContextVar[float | None] = ContextVar(
    "stream_finalization_deadline", default=None
)


def finalization_scope() -> anyio.CancelScope:
    """A shielded scope that ends at the task's shared finalization deadline.

    The first caller on a task fixes the deadline; later callers on the same
    task, deeper or shallower in the chain, share it.
    """
    deadline = _finalization_deadline.get()
    if deadline is None:
        deadline = anyio.current_time() + FINALIZATION_BUDGET_SECONDS
        _finalization_deadline.set(deadline)
    return anyio.CancelScope(shield=True, deadline=deadline)


def clear_finalization_deadline() -> None:
    """Forget the deadline once the outermost owner has finished."""
    _finalization_deadline.set(None)


@contextmanager
def finalizing(step: str) -> Generator[None, None, None]:
    """Run one cleanup step under the shared, shielded finalization budget.

    A step that outlives the budget is cut off and logged; the steps after it
    still run (each sees the same, now past, deadline and is cut off at its
    first await), so one hung close never skips the rest.
    """
    with finalization_scope() as scope:
        yield
    if scope.cancelled_caught:
        logger.warning(
            "Stream finalization step '%s' exceeded the %.0fs budget and was cut off",
            step,
            FINALIZATION_BUDGET_SECONDS,
        )


async def aclose_if_possible(source: object) -> None:
    aclose = getattr(source, "aclose", None)
    if aclose is not None:
        await aclose()


@asynccontextmanager
async def closing(source: AsyncIterable[T]) -> AsyncGenerator[AsyncIterable[T]]:
    """Close ``source`` when its consumer stops, if it can be closed.

    ``contextlib.aclosing`` for sources typed as plain iterables: a generator
    is closed, anything without ``aclose`` is left alone.
    """
    try:
        yield source
    finally:
        await aclose_if_possible(source)


class OwnedAsyncGenerator(AsyncGenerator[T, None]):
    """A generator whose resources are released even if it never starts.

    Closing a generator that has not been started runs nothing, so a stream
    prepared before the response begins (a provider request already in
    flight, MCP connections already open) would leak if the body is never
    iterated. ``release`` runs in that case instead of the generator's
    ``finally``. Once started, closing is the generator's own.
    """

    def __init__(
        self,
        generator: AsyncGenerator[T, None],
        *,
        release: Callable[[], Awaitable[None]],
    ) -> None:
        self._generator = generator
        self._release = release
        self._started = False
        self._closed = False

    def __aiter__(self) -> OwnedAsyncGenerator[T]:
        return self

    async def __anext__(self) -> T:
        self._started = True
        return await self._generator.__anext__()

    async def asend(self, value: None) -> T:
        self._started = True
        return await self._generator.asend(value)

    async def athrow(
        self,
        typ: type[BaseException] | BaseException,
        val: BaseException | object = None,
        tb: TracebackType | None = None,
        /,
    ) -> T:
        self._started = True
        if isinstance(typ, BaseException):
            return await self._generator.athrow(typ, None, tb)
        return await self._generator.athrow(typ, val, tb)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._started:
            await self._generator.aclose()
        else:
            await self._release()
