import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from starlette.requests import ClientDisconnect

from eneo.object_content.content import ContentRead
from eneo.object_content.content_service import detach_content_read
from eneo.server.protocol.downloads import ClosingStreamingResponse


def _scope(*, spec_version: str) -> dict[str, object]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/download",
        "raw_path": b"/download",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
        "root_path": "",
    }


async def _receive_disconnect() -> dict[str, str]:
    return {"type": "http.disconnect"}


@pytest.mark.asyncio
async def test_closes_when_disconnect_arrives_before_body_iteration():
    close = AsyncMock()

    async def chunks() -> AsyncGenerator[bytes, None]:
        yield b"unread"

    response = ClosingStreamingResponse(chunks(), close=close)
    await response(
        _scope(spec_version="2.3"),
        _receive_disconnect,
        AsyncMock(),
    )

    close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_disconnect_during_read_finishes_async_content_cleanup():
    source_started = asyncio.Event()
    block_source = asyncio.Event()
    exit_completed = False

    async def chunks() -> AsyncGenerator[bytes, None]:
        source_started.set()
        await block_source.wait()
        yield b"unreachable"

    @asynccontextmanager
    async def read_context() -> AsyncGenerator[ContentRead, None]:
        nonlocal exit_completed
        try:
            yield ContentRead(
                chunks=chunks(),
                content_length=11,
                media_type="application/octet-stream",
                content_range=None,
            )
        finally:
            await asyncio.sleep(0)
            exit_completed = True

    async def receive_after_read_starts() -> dict[str, str]:
        await source_started.wait()
        return {"type": "http.disconnect"}

    opened = await detach_content_read(read_context())
    response = ClosingStreamingResponse(opened.chunks, close=opened.aclose)
    await response(
        _scope(spec_version="2.3"),
        receive_after_read_starts,
        AsyncMock(),
    )

    assert exit_completed


@pytest.mark.asyncio
async def test_closes_when_body_send_fails_after_first_chunk():
    close = AsyncMock()

    async def chunks() -> AsyncGenerator[bytes, None]:
        yield b"first"
        yield b"second"

    async def fail_on_body(message: dict[str, object]) -> None:
        if message["type"] == "http.response.body":
            raise OSError("client disconnected")

    response = ClosingStreamingResponse(chunks(), close=close)
    with pytest.raises(ClientDisconnect):
        await response(
            _scope(spec_version="2.4"),
            _receive_disconnect,
            fail_on_body,
        )

    close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_closes_once_after_normal_streaming_and_repeated_calls():
    close = AsyncMock()
    sent: list[dict[str, object]] = []

    async def chunks() -> AsyncGenerator[bytes, None]:
        yield b"first"
        yield b"second"

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    response = ClosingStreamingResponse(chunks(), close=close)
    await response(
        _scope(spec_version="2.4"),
        _receive_disconnect,
        send,
    )
    await response(
        _scope(spec_version="2.4"),
        _receive_disconnect,
        send,
    )

    body = b"".join(
        message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    )
    assert body == b"firstsecond"
    close.assert_awaited_once_with()
