"""A client that hangs up on a streamed answer, over a real socket.

uvicorn, RequestContextMiddleware (BaseHTTPMiddleware, whose unbuffered
inner stream parks the body at ``send`` once the client is gone) and a raw
TCP client that closes mid-stream: the body's cleanup must run promptly, on
the task that streamed it, and finish its awaits.
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

import pytest
import uvicorn
from fastapi import FastAPI

from eneo.main.stream_lifecycle import finalizing
from eneo.server.middleware.request_context import RequestContextMiddleware
from eneo.server.protocol.sse import ClosingEventSourceResponse


@asynccontextmanager
async def _serve(app: FastAPI) -> AsyncIterator[int]:
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="warning", lifespan="off", ws="none"
    )
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve())
    while not server.started:
        if serving.done():
            serving.result()
        await asyncio.sleep(0.01)
    try:
        yield server.servers[0].sockets[0].getsockname()[1]
    finally:
        server.should_exit = True
        await serving


async def _read_events(port: int, count: int) -> None:
    """Open the stream, read ``count`` events, hang up."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        b"GET /stream HTTP/1.1\r\nHost: test\r\nAccept: text/event-stream\r\n\r\n"
    )
    await writer.drain()
    seen = 0
    while seen < count:
        line = await reader.readline()
        assert line, "the server closed the stream first"
        if line.startswith(b"data:"):
            seen += 1
    writer.close()
    await writer.wait_closed()


class _Cleanup:
    def __init__(self) -> None:
        self.iterating_task: asyncio.Task[object] | None = None
        self.finished_on: asyncio.Task[object] | None = None
        self.done = asyncio.Event()


def _app(body: AsyncGenerator[str, None]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/stream")
    async def stream() -> ClosingEventSourceResponse:
        return ClosingEventSourceResponse(body, ping=1000)

    return app


@pytest.mark.asyncio
async def test_hanging_up_mid_stream_runs_the_cleanup_on_the_streaming_task():
    cleanup = _Cleanup()

    async def body() -> AsyncGenerator[str, None]:
        cleanup.iterating_task = asyncio.current_task()
        try:
            while True:
                yield "token"
                await asyncio.sleep(0.005)
        finally:
            with finalizing("cleanup"):
                await asyncio.sleep(0.01)
                cleanup.finished_on = asyncio.current_task()
                cleanup.done.set()

    async with _serve(_app(body())) as port:
        await _read_events(port, 2)
        async with asyncio.timeout(3):
            await cleanup.done.wait()

    assert cleanup.finished_on is cleanup.iterating_task


@pytest.mark.asyncio
async def test_hanging_up_during_work_stops_it_and_finishes_the_cleanup():
    # Rests on Starlette's BaseHTTPMiddleware forwarding ``http.disconnect`` to
    # the inner app while the body is parked in an await (no send pending):
    # that message is what stops the work. If a Starlette bump stops the
    # forwarding, this times out waiting for the cleanup and the assumption,
    # not the response, is what broke.
    cleanup = _Cleanup()
    work_cancelled = asyncio.Event()

    async def body() -> AsyncGenerator[str, None]:
        cleanup.iterating_task = asyncio.current_task()
        try:
            yield "token"
            try:
                await asyncio.Event().wait()  # a model request or tool call
            except asyncio.CancelledError:
                work_cancelled.set()
                raise
        finally:
            with finalizing("cleanup"):
                await asyncio.sleep(0.01)
                cleanup.finished_on = asyncio.current_task()
                cleanup.done.set()

    async with _serve(_app(body())) as port:
        await _read_events(port, 1)
        async with asyncio.timeout(3):
            await cleanup.done.wait()

    assert work_cancelled.is_set()
    assert cleanup.finished_on is cleanup.iterating_task
