import asyncio
from collections.abc import AsyncGenerator

import pytest

from eneo.main.stream_lifecycle import finalizing
from eneo.server.protocol.sse import ClosingEventSourceResponse, closing


def _scope() -> dict[str, object]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/stream",
        "raw_path": b"/stream",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
        "root_path": "",
    }


class _Client:
    """Reads the first event, then disconnects.

    Later body sends block like BaseHTTPMiddleware's unbuffered stream does
    once the outer response has stopped reading.
    """

    def __init__(self, *, disconnect_before_body: bool = False) -> None:
        self.first_event_sent = asyncio.Event()
        self._request_delivered = False
        self._disconnect_before_body = disconnect_before_body

    async def receive(self) -> dict[str, object]:
        if not self._request_delivered:
            self._request_delivered = True
            return {"type": "http.request", "body": b"", "more_body": False}
        if not self._disconnect_before_body:
            await self.first_event_sent.wait()
        return {"type": "http.disconnect"}

    async def send(self, message: dict[str, object]) -> None:
        if message["type"] != "http.response.body":
            if self._disconnect_before_body:
                # The response has started but no body is read; the client
                # is gone before the first token.
                await asyncio.Event().wait()
            return
        if self.first_event_sent.is_set():
            await asyncio.Event().wait()
        self.first_event_sent.set()


@pytest.mark.asyncio
async def test_disconnect_at_a_yield_closes_the_body_on_its_own_task():
    iterating_task: asyncio.Task[object] | None = None
    closed_on: asyncio.Task[object] | None = None
    exit_reason: type[BaseException] | None = None

    async def body() -> AsyncGenerator[str, None]:
        nonlocal iterating_task, closed_on, exit_reason
        iterating_task = asyncio.current_task()
        try:
            while True:
                yield "token"
        except BaseException as exc:
            exit_reason = type(exc)
            raise
        finally:
            # Cleanup such as closing MCP connections awaits; it must survive
            # the cancelled task group.
            await asyncio.sleep(0)
            closed_on = asyncio.current_task()

    client = _Client()
    await ClosingEventSourceResponse(body())(_scope(), client.receive, client.send)

    assert exit_reason is GeneratorExit
    assert closed_on is not None
    assert closed_on is iterating_task


@pytest.mark.asyncio
async def test_disconnect_during_work_cancels_it_and_never_resumes_the_loop():
    rounds = 0
    work_cancelled = False

    async def tool_loop() -> AsyncGenerator[str, None]:
        nonlocal rounds, work_cancelled
        while True:
            rounds += 1
            yield f"round {rounds}"
            try:
                await asyncio.Event().wait()  # a model request or tool call
            except asyncio.CancelledError:
                work_cancelled = True
                raise

    client = _Client()
    await ClosingEventSourceResponse(tool_loop())(_scope(), client.receive, client.send)

    assert work_cancelled
    assert rounds == 1


@pytest.mark.asyncio
async def test_disconnect_during_work_lets_the_owner_finish_its_async_cleanup():
    """The cancellation lands inside the body, before the response's own
    cleanup runs; an owner's finalizing() keeps it out of the cleanup."""
    cleanup_finished = False

    async def body() -> AsyncGenerator[str, None]:
        nonlocal cleanup_finished
        try:
            yield "token"
            await asyncio.Event().wait()
        finally:
            with finalizing("owner cleanup"):
                await asyncio.sleep(0.01)
                cleanup_finished = True

    client = _Client()
    await ClosingEventSourceResponse(body())(_scope(), client.receive, client.send)

    assert cleanup_finished


@pytest.mark.asyncio
async def test_a_disconnect_before_the_body_starts_still_closes_its_sources():
    """An unstarted generator runs nothing when closed, so the response closes
    the streams behind it directly."""
    source_closed = False
    body_started = False

    class _Source:
        async def aclose(self) -> None:
            nonlocal source_closed
            source_closed = True

    async def body() -> AsyncGenerator[str, None]:
        nonlocal body_started
        body_started = True
        yield "token"

    client = _Client(disconnect_before_body=True)
    response = ClosingEventSourceResponse(body(), closes=[_Source()])
    await response(_scope(), client.receive, client.send)

    assert not body_started
    assert source_closed


@pytest.mark.asyncio
async def test_closing_closes_the_source_when_the_consumer_is_closed():
    source_closed_on: asyncio.Task[object] | None = None

    async def source() -> AsyncGenerator[str, None]:
        nonlocal source_closed_on
        try:
            while True:
                yield "chunk"
        finally:
            source_closed_on = asyncio.current_task()

    async def consumer() -> AsyncGenerator[str, None]:
        async with closing(source()) as chunks:
            async for chunk in chunks:
                yield chunk

    stream = consumer()
    assert await anext(stream) == "chunk"
    await stream.aclose()

    assert source_closed_on is asyncio.current_task()
