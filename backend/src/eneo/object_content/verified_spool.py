import asyncio
from collections.abc import AsyncGenerator, Awaitable
from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile, SpooledTemporaryFile
from typing import BinaryIO, TypeVar, cast

from eneo.object_content.content import (
    ByteRange,
    ContentRead,
    ObjectContentIntegrityError,
    ObjectContentUnavailableError,
)

_Result = TypeVar("_Result")


async def settle_read_operation(operation: Awaitable[_Result]) -> _Result:
    """Settle owned read resources before propagating cancellation."""
    task = asyncio.ensure_future(operation)
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            cancellation = cancellation or error
        except BaseException:
            if cancellation is not None:
                raise cancellation
            raise
    if cancellation is not None:
        try:
            task.result()
        except BaseException:
            pass
        raise cancellation
    return task.result()


class VerifiedSpoolIntegrityError(ObjectContentIntegrityError):
    def __init__(self, message: str, *, observed_sha256: bytes) -> None:
        super().__init__(message)
        self.observed_sha256 = observed_sha256


class VerifiedSpool:
    """Own verification bytes until close or a caller renames the verified path."""

    def __init__(self, file: BinaryIO, path: Path | None, io_chunk_bytes: int):
        self._file = file
        self._path = path
        self._io_chunk_bytes = io_chunk_bytes
        self._digest = sha256()
        self._size = 0

    @classmethod
    @asynccontextmanager
    async def open(
        cls,
        *,
        io_chunk_bytes: int,
        memory_bytes: int | None = None,
    ) -> AsyncGenerator["VerifiedSpool"]:
        try:
            file = (
                NamedTemporaryFile(mode="w+b", delete=False)
                if memory_bytes is None
                else SpooledTemporaryFile(max_size=memory_bytes, mode="w+b")
            )
        except OSError as error:
            raise ObjectContentUnavailableError(
                "Verified spool creation failed"
            ) from error
        path = Path(file.name) if memory_bytes is None else None
        spool = cls(cast(BinaryIO, file), path, io_chunk_bytes)
        has_primary_error = False
        try:
            yield spool
        except BaseException:
            has_primary_error = True
            raise
        finally:
            cleanup_error: BaseException | None = None
            try:
                await settle_read_operation(asyncio.to_thread(file.close))
            except BaseException as error:
                cleanup_error = error
            try:
                if path is not None:
                    path.unlink(missing_ok=True)
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
            if not has_primary_error and cleanup_error is not None:
                if isinstance(cleanup_error, OSError):
                    raise ObjectContentUnavailableError(
                        "Verified spool cleanup failed"
                    ) from cleanup_error
                raise cleanup_error

    async def write(self, chunk: bytes) -> None:
        try:
            written = await settle_read_operation(
                asyncio.to_thread(self._file.write, chunk)
            )
        except OSError as error:
            raise ObjectContentUnavailableError(
                "Verified spool write failed"
            ) from error
        if written != len(chunk):
            raise ObjectContentUnavailableError(
                "Verified spool accepted a partial write"
            )
        self._digest.update(chunk)
        self._size += len(chunk)

    def verify(self, *, expected_sha256: bytes, expected_size_bytes: int) -> None:
        observed = self._digest.digest()
        if self._size != expected_size_bytes:
            raise VerifiedSpoolIntegrityError(
                "Content bytes do not match the canonical size",
                observed_sha256=observed,
            )
        if observed != expected_sha256:
            raise VerifiedSpoolIntegrityError(
                "Content bytes do not match the canonical SHA-256",
                observed_sha256=observed,
            )

    @asynccontextmanager
    async def read(
        self,
        *,
        media_type: str,
        byte_range: ByteRange | None = None,
        require_local_path: bool = False,
        start: int | None = None,
    ) -> AsyncGenerator[ContentRead]:
        length = self._size if byte_range is None else byte_range.content_length
        offset = (
            (0 if byte_range is None else byte_range.start) if start is None else start
        )
        try:
            await settle_read_operation(asyncio.to_thread(self._file.seek, offset))
        except OSError as error:
            raise ObjectContentUnavailableError("Verified spool seek failed") from error

        async def chunks() -> AsyncGenerator[bytes]:
            remaining = length
            while remaining:
                try:
                    chunk = await settle_read_operation(
                        asyncio.to_thread(
                            self._file.read, min(self._io_chunk_bytes, remaining)
                        )
                    )
                except OSError as error:
                    raise ObjectContentUnavailableError(
                        "Verified spool read failed"
                    ) from error
                if not chunk:
                    raise ObjectContentUnavailableError(
                        "Verified spool ended before its length"
                    )
                remaining -= len(chunk)
                yield chunk

        stream = chunks()
        try:
            yield ContentRead(
                chunks=stream,
                content_length=length,
                media_type=media_type,
                content_range=None
                if byte_range is None
                else byte_range.response_header,
                verified_path=self._path
                if require_local_path and byte_range is None
                else None,
            )
        finally:
            await stream.aclose()
