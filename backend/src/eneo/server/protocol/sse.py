from collections.abc import AsyncGenerator, AsyncIterable
from contextlib import asynccontextmanager
from typing import TypeVar, cast

import anyio
from sse_starlette import EventSourceResponse
from starlette.types import Send

T = TypeVar("T")

# Bounds the shielded cleanup so a hung MCP disconnect cannot hold the
# request task (or a graceful shutdown) open indefinitely.
STREAM_CLOSE_TIMEOUT_SECONDS = 10


async def _aclose(source: object) -> None:
    aclose = getattr(source, "aclose", None)
    if aclose is not None:
        await aclose()


class ClosingEventSourceResponse(EventSourceResponse):
    """Close the body iterator on the task that iterated it.

    On a client disconnect sse-starlette cancels the streaming task. When the
    cancellation lands in ``send`` rather than inside the generator, the
    generator stays suspended at its ``yield``: its ``finally`` blocks (partial
    answer save, MCP proxy close) then run only when the garbage collector
    finalizes it, on another task, where the MCP proxy cannot release the
    connections it opened.
    """

    async def stream_response(self, send: Send) -> None:
        try:
            await super().stream_response(send)
        finally:
            body = cast(object, self.body_iterator)  # pyright: ignore[reportUnknownMemberType]
            with anyio.move_on_after(STREAM_CLOSE_TIMEOUT_SECONDS, shield=True):
                await _aclose(body)


@asynccontextmanager
async def closing(source: AsyncIterable[T]) -> AsyncGenerator[AsyncIterable[T]]:
    """Close ``source`` when the consumer stops; ``async for`` never does."""
    try:
        yield source
    finally:
        await _aclose(source)
