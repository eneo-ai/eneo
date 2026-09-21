"""Own one measured audio spool for a flow transcription attempt.

Object-store downloads stream to disk; inline downloads hydrate once within the
deployment's inline ceiling and release their payload before transcription.
Signed-URL submission awaits verification of the Vemsa-to-Eneo route in eneo-hy7c.
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias
from uuid import UUID

from eneo.files import audio
from eneo.files.file_service import FileDownload

OpenAudioDownload: TypeAlias = Callable[[UUID], Awaitable[FileDownload]]


@dataclass(frozen=True, slots=True)
class SpooledAudio:
    path: Path
    duration_seconds: float
    digest: str
    byte_size: int
    mimetype: str
    filename: str

    async def aclose(self) -> None:
        self.path.unlink(missing_ok=True)


async def _close_download(download: FileDownload) -> None:
    async def close() -> None:
        try:
            await download.chunks.aclose()
        finally:
            await download.aclose()

    cleanup = asyncio.create_task(close())
    cancelled = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            cancelled = True
    cleanup.result()
    if cancelled:
        raise asyncio.CancelledError


async def spool_audio(
    file_id: UUID, *, open_audio_download: OpenAudioDownload
) -> SpooledAudio:
    download = await open_audio_download(file_id)
    path: Path | None = None
    try:
        try:
            mimetype = download.media_type
            filename = download.filename
            if not audio.AudioMimeTypes.has_value(mimetype):
                raise ValueError("File needs to be an audio file")
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=Path(filename).suffix or ".audio"
            ) as target:
                path = Path(target.name)
                byte_size = 0
                async for chunk in download.chunks:
                    byte_size += len(chunk)
                    if byte_size > download.content_length:
                        raise ValueError("Audio download exceeds its declared length")
                    target.write(chunk)
                    del chunk
                if byte_size != download.content_length:
                    raise ValueError(
                        "Audio download does not match its declared length"
                    )
        finally:
            await _close_download(download)
            del download

        duration_seconds = await audio.measure_duration(str(path))
        # Wait for the file reader on cancellation before removing its spool.
        digest = await _measure_digest(path)
        return SpooledAudio(
            path=path,
            duration_seconds=duration_seconds,
            digest=digest,
            byte_size=byte_size,
            mimetype=mimetype,
            filename=filename,
        )
    except BaseException:
        if path is not None:
            path.unlink(missing_ok=True)
        raise


async def _measure_digest(path: Path) -> str:
    worker = asyncio.create_task(asyncio.to_thread(_digest_file, path))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        while not worker.done():
            with suppress(asyncio.CancelledError, Exception):
                await asyncio.shield(worker)
        if not worker.cancelled():
            worker.exception()
        raise


def _digest_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
