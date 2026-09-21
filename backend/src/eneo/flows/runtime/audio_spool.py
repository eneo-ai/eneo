"""Own one original audio file for a flow transcription attempt.

Object-store audio reuses the verified download's named disk file; inline audio
is hydrated once within the deployment's inline ceiling, written once to disk,
and released before transcription. Both reuse the download's verified digest.
Only remote submission measures and caches duration; local transcription applies
its decode limits during its own decode. Remote acceptance releases the original.
Signed-URL submission awaits verification of the Vemsa-to-Eneo route in eneo-hy7c.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeAlias
from uuid import UUID

from eneo.files import audio
from eneo.files.file_service import FileDownload

OpenAudioDownload: TypeAlias = Callable[[UUID], Awaitable[FileDownload]]


@dataclass(frozen=True, slots=True)
class SpooledAudio:
    path: Path
    digest: str
    byte_size: int
    mimetype: str
    filename: str
    _duration: asyncio.Task[float] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    async def measure_duration(self) -> float:
        task = self._duration
        if task is None:
            task = asyncio.create_task(audio.measure_duration(str(self.path)))
            object.__setattr__(self, "_duration", task)
        return await task

    async def aclose(self) -> None:
        task = self._duration
        cancelled = False
        if task is not None:
            if not task.done():
                task.cancel()
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    cancelled = True
                except Exception:
                    break
            if not task.cancelled():
                task.exception()
        self.path.unlink(missing_ok=True)
        if cancelled:
            raise asyncio.CancelledError


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
            digest = download.sha256.hex()
            verified_path = download.verified_path
            if not audio.AudioMimeTypes.has_value(mimetype):
                raise ValueError("File needs to be an audio file")
            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=Path(filename).suffix or ".audio",
                dir=verified_path.parent if verified_path is not None else None,
            ) as target:
                path = Path(target.name)
                byte_size = download.content_length
                if verified_path is None:
                    byte_size = 0
                    async for chunk in download.chunks:
                        byte_size += len(chunk)
                        if byte_size > download.content_length:
                            raise ValueError(
                                "Audio download exceeds its declared length"
                            )
                        target.write(chunk)
                        del chunk
                    if byte_size != download.content_length:
                        raise ValueError(
                            "Audio download does not match its declared length"
                        )
            if verified_path is not None:
                verified_path.replace(path)
        finally:
            await _close_download(download)
            del download

        return SpooledAudio(
            path=path,
            digest=digest,
            byte_size=byte_size,
            mimetype=mimetype,
            filename=filename,
        )
    except BaseException:
        if path is not None:
            path.unlink(missing_ok=True)
        raise
