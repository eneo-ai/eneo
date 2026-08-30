from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from starlette.requests import ClientDisconnect

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
