"""Deterministic release of a streamed turn's resources.

A streamed answer is a chain of async generators: the provider stream, the
model/tool loop, the completion service's typed chunks, the assistant's
accumulator and the SSE body. ``async for`` never closes the generator it
reads, so every link closes its source (``closing``), and the response closes
the body on the task that iterated it.

Two rules make the ``finally`` blocks along that chain reliable:

- Cleanup runs inside ``finalizing(...)``: a shielded cancel scope with one
  deadline shared by every link of the turn, so a disconnect that lands
  mid-await cannot cut the cleanup short, and the request waits at most one
  budget for it. A step cut off by the deadline is logged. An MCP connection
  it was waiting for is cancelled and unwinds on its own; a provider stream
  closes under its own shield.
- A generator that never started cannot run its ``finally``. Where resources
  are acquired before the first iteration, ``OwnedAsyncGenerator`` runs the
  owner's release instead.

The budget belongs to an owner frame (``finalization_owner``): the outermost
consumer of the answer holds one around every step it drives
(``OwnedAsyncGenerator``), and the SSE response around its close sequence.
The first ``finalizing`` step inside the frame fixes the deadline, every step
inside shares it, however the chain unwinds, and the frame forgets it on
exit, so a task may finalize any number of turns. A step outside any frame is
its own owner. Ownership is per task: a task created inside a frame (an MCP
connection host, a gathered disconnect, the partial-answer save) inherits the
context but not the ownership, and starts a budget of its own should it ever
finalize anything.

Cancel scopes may only be entered here, on the task doing the cleanup, after
no task-bound scope (an MCP connection's) remains on it; the connection host
in ``mcp_client`` keeps those on a task of their own.
"""

from __future__ import annotations

import asyncio
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
# The task holding the current owner frames, and how many are open on it.
_finalization_owner_task: ContextVar[asyncio.Task[object] | None] = ContextVar(
    "stream_finalization_owner_task", default=None
)
_finalization_owners: ContextVar[int] = ContextVar(
    "stream_finalization_owners", default=0
)


def finalization_deadline() -> float | None:
    """The deadline of the cleanup in progress on this task, if one is fixed."""
    return _finalization_deadline.get()


@contextmanager
def finalization_owner() -> Generator[None, None, None]:
    """Hold the task's finalization budget for the duration of the block.

    The outermost frame on a task forgets the deadline when it exits; frames
    inside it share whatever deadline the first step fixed.
    """
    current = asyncio.current_task()
    owners = _finalization_owners.get()
    if owners > 0 and _finalization_owner_task.get() is current:
        _finalization_owners.set(owners + 1)
        try:
            yield
        finally:
            _finalization_owners.set(owners)
        return

    # A new root: either no frame is open, or the open ones belong to the
    # task this context was copied from.
    _finalization_owner_task.set(current)
    _finalization_owners.set(1)
    _finalization_deadline.set(None)
    try:
        yield
    finally:
        _finalization_owners.set(0)
        _finalization_owner_task.set(None)
        _finalization_deadline.set(None)


def _current_deadline() -> float:
    deadline = _finalization_deadline.get()
    if deadline is None:
        deadline = anyio.current_time() + FINALIZATION_BUDGET_SECONDS
        _finalization_deadline.set(deadline)
    return deadline


@contextmanager
def finalizing(step: str) -> Generator[None, None, None]:
    """Run one cleanup step under the owner's shielded finalization budget.

    A step that outlives the budget is cut off and logged; the steps after it
    still run (each sees the same, now past, deadline and is cut off at its
    first await), so one hung close never skips the rest.
    """
    with finalization_owner():
        deadline = _current_deadline()
        spent_on_entry = anyio.current_time() >= deadline
        with anyio.CancelScope(shield=True, deadline=deadline) as scope:
            yield
    if scope.cancelled_caught and spent_on_entry:
        logger.warning(
            "Stream finalization step '%s' was cut off at its first await: "
            "the %.0fs budget was already spent",
            step,
            FINALIZATION_BUDGET_SECONDS,
        )
    elif scope.cancelled_caught:
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
async def closing(
    source: AsyncIterable[T], step: str = "source stream"
) -> AsyncGenerator[AsyncIterable[T]]:
    """Close ``source`` when its consumer stops, if it can be closed.

    ``contextlib.aclosing`` for sources typed as plain iterables, run as a
    finalization step: a generator is closed, anything without ``aclose`` is
    left alone.
    """
    try:
        yield source
    finally:
        with finalizing(step):
            await aclose_if_possible(source)


class OwnedAsyncGenerator(AsyncGenerator[T, None]):
    """A generator whose resources are released even if it never starts.

    Closing a generator that has not been started runs nothing, so a stream
    prepared before the response begins (a provider request already in
    flight, MCP connections already open) would leak if the body is never
    iterated. ``release`` runs in that case instead of the generator's
    ``finally``. Once started, closing is the generator's own.

    Every step it drives runs in a finalization owner frame, so whatever
    cleanup the step triggers, by closing or by an exception unwinding the
    chain, shares one budget and leaves none behind on the task.
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
        with finalization_owner():
            return await self._generator.__anext__()

    async def asend(self, value: None) -> T:
        self._started = True
        with finalization_owner():
            return await self._generator.asend(value)

    async def athrow(
        self,
        typ: type[BaseException] | BaseException,
        val: BaseException | object = None,
        tb: TracebackType | None = None,
        /,
    ) -> T:
        del tb
        if isinstance(typ, BaseException):
            exc = typ
        elif isinstance(val, BaseException):
            exc = val
        else:
            exc = typ(val) if val is not None else typ()
        if not self._started:
            # Thrown into before it started, a generator ends without running
            # its body: release what the body would have owned.
            await self.aclose()
            raise exc
        with finalization_owner():
            return await self._generator.athrow(exc)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        with finalization_owner():
            if self._started:
                await self._generator.aclose()
            else:
                await self._release()
