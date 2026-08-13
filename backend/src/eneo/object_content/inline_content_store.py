import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from hashlib import sha256

from eneo.object_content.content import (
    ByteRange,
    CapturedContent,
    ContentRead,
    ContentTooLargeError,
    ObjectContentIntegrityError,
)


class InlineContentStore:
    """Bound PostgreSQL-inline materialization and verified reads."""

    def __init__(self, *, maximum_size_bytes: int, io_chunk_bytes: int) -> None:
        if maximum_size_bytes < 1:
            raise ValueError("Inline maximum size must be positive")
        if io_chunk_bytes < 1:
            raise ValueError("Inline I/O chunk size must be positive")
        self._maximum_size_bytes = maximum_size_bytes
        self._io_chunk_bytes = io_chunk_bytes

    @property
    def maximum_size_bytes(self) -> int:
        return self._maximum_size_bytes

    async def materialize(self, content: CapturedContent) -> bytes:
        if content.size_bytes > self._maximum_size_bytes:
            raise ContentTooLargeError(self._maximum_size_bytes)

        def read_bounded() -> bytes:
            original_position = content.file.tell()
            try:
                content.file.seek(0)
                return content.file.read(self._maximum_size_bytes + 1)
            finally:
                content.file.seek(original_position)

        payload = await asyncio.to_thread(read_bounded)
        if len(payload) != content.size_bytes:
            raise ObjectContentIntegrityError(
                "Captured inline bytes do not match the canonical size"
            )
        if sha256(payload).digest() != content.sha256:
            raise ObjectContentIntegrityError(
                "Captured inline bytes do not match the canonical SHA-256"
            )
        return payload

    @asynccontextmanager
    async def open_verified_read(
        self,
        payload: bytes,
        *,
        expected_sha256: bytes,
        expected_size_bytes: int,
        expected_media_type: str,
        byte_range: ByteRange | None = None,
    ) -> AsyncGenerator[ContentRead, None]:
        if len(payload) != expected_size_bytes:
            raise ObjectContentIntegrityError(
                "Inline bytes do not match the canonical size"
            )
        if sha256(payload).digest() != expected_sha256:
            raise ObjectContentIntegrityError(
                "Inline bytes do not match the canonical SHA-256"
            )
        if byte_range is not None and byte_range.total != expected_size_bytes:
            raise ObjectContentIntegrityError(
                "Requested byte range does not match the canonical content size"
            )

        start = 0 if byte_range is None else byte_range.start
        content_length = (
            expected_size_bytes if byte_range is None else byte_range.content_length
        )

        async def chunks() -> AsyncGenerator[bytes, None]:
            stop = start + content_length
            for offset in range(start, stop, self._io_chunk_bytes):
                yield payload[offset : min(offset + self._io_chunk_bytes, stop)]

        stream = chunks()
        try:
            yield ContentRead(
                chunks=stream,
                content_length=content_length,
                media_type=expected_media_type,
                content_range=(
                    None if byte_range is None else byte_range.response_header
                ),
            )
        finally:
            await stream.aclose()
