import asyncio
from collections.abc import AsyncGenerator
from types import TracebackType

import pytest

from eneo.object_content.content import ContentRead
from eneo.object_content.content_service import detach_content_read


class _ReadContext:
    def __init__(
        self,
        chunks: AsyncGenerator[bytes, None],
        *,
        suppress_errors: bool = False,
    ) -> None:
        self._read = ContentRead(
            chunks=chunks,
            content_length=6,
            media_type="application/octet-stream",
            content_range=None,
        )
        self.exits: list[tuple[type[BaseException] | None, BaseException | None]] = []
        self._suppress_errors = suppress_errors

    async def __aenter__(self) -> ContentRead:
        return self._read

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        self.exits.append((exc_type, exc_value))
        return self._suppress_errors


class _BlockingExitReadContext(_ReadContext):
    def __init__(self, chunks: AsyncGenerator[bytes, None]) -> None:
        super().__init__(chunks)
        self.exit_started = asyncio.Event()
        self.allow_exit = asyncio.Event()
        self.exit_completed = False

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        self.exits.append((exc_type, exc_value))
        self.exit_started.set()
        await self.allow_exit.wait()
        self.exit_completed = True
        return None


@pytest.mark.asyncio
async def test_detached_content_read_closes_once_after_streaming() -> None:
    async def chunks() -> AsyncGenerator[bytes, None]:
        yield b"abc"
        yield b"def"

    context = _ReadContext(chunks())
    opened = await detach_content_read(context)

    assert b"".join([chunk async for chunk in opened.chunks]) == b"abcdef"
    await opened.aclose()

    assert context.exits == [(None, None)]


@pytest.mark.asyncio
async def test_detached_content_read_closes_with_stream_error() -> None:
    error = OSError("read failed")

    async def chunks() -> AsyncGenerator[bytes, None]:
        yield b"abc"
        raise error

    context = _ReadContext(chunks())
    opened = await detach_content_read(context)

    with pytest.raises(OSError, match="read failed"):
        _ = [chunk async for chunk in opened.chunks]
    await opened.aclose()

    assert context.exits == [(OSError, error)]


@pytest.mark.asyncio
async def test_detached_content_read_honors_context_error_suppression() -> None:
    error = OSError("suppressed")

    async def chunks() -> AsyncGenerator[bytes, None]:
        yield b"abc"
        raise error

    context = _ReadContext(chunks(), suppress_errors=True)
    opened = await detach_content_read(context)

    assert [chunk async for chunk in opened.chunks] == [b"abc"]
    assert context.exits == [(OSError, error)]


@pytest.mark.asyncio
async def test_detached_content_read_finishes_exit_after_closer_is_cancelled() -> None:
    async def chunks() -> AsyncGenerator[bytes, None]:
        yield b"unused"

    context = _BlockingExitReadContext(chunks())
    opened = await detach_content_read(context)
    first_close = asyncio.create_task(opened.aclose())
    await context.exit_started.wait()

    first_close.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_close
    context.allow_exit.set()
    await opened.aclose()

    assert context.exit_completed
    assert context.exits == [(None, None)]
