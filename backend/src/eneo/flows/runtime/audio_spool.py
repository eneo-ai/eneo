"""Own one original audio file for a flow transcription attempt.

Object-store audio reuses the verified download's named disk file; inline audio
is hydrated once within the deployment's inline ceiling, written once to disk,
and released before transcription. Both reuse the download's verified digest.
Duration is cached from the local bounded decode, or measured lazily when only
the remote engine runs. Remote acceptance releases the original.
Signed-URL submission awaits verification of the Vemsa-to-Eneo route in eneo-hy7c.
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeAlias, TypeVar
from uuid import UUID

from eneo.files import audio
from eneo.files.file_service import FileDownload

OpenAudioDownload: TypeAlias = Callable[[UUID], Awaitable[FileDownload]]
_Part = TypeVar("_Part")


@dataclass(frozen=True, slots=True)
class SpooledAudio:
    path: Path
    digest: str
    byte_size: int
    mimetype: str
    filename: str
    _duration: asyncio.Future[float] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def cache_duration(self, duration_seconds: float) -> None:
        if self._duration is None:
            duration: asyncio.Future[float] = asyncio.get_running_loop().create_future()
            duration.set_result(duration_seconds)
            object.__setattr__(self, "_duration", duration)

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


async def spool_recording(
    parts: Sequence[_Part],
    spool: Callable[[_Part], Awaitable[SpooledAudio]],
    *,
    limits: audio.AudioDecodeLimits | None = None,
) -> tuple[tuple[SpooledAudio, ...], SpooledAudio, tuple[float, ...]]:
    """The parts of one recording, each spooled and decoded onto one 16 kHz WAV
    before the next is fetched, so a recording over the decode limit stops at
    the part that crosses it. Returns the part spools, the joined WAV (digest
    taken once its header has its final lengths) and each part's length."""
    spooled: list[SpooledAudio] = []
    durations: list[float] = []
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as target:
        path = Path(target.name)
    try:
        with (
            path.open("wb") as target,
            audio.joined_wav(
                target, limits=limits or audio.AudioDecodeLimits.from_settings()
            ) as joined,
        ):
            for part in parts:
                spooled.append(await spool(part))
                durations.append(await joined.append(str(spooled[-1].path)))
        digest = await asyncio.to_thread(_sha256_of, path)
    except BaseException:
        path.unlink(missing_ok=True)
        for part_spool in spooled:
            await part_spool.aclose()
        raise
    recording = SpooledAudio(
        path=path,
        digest=digest,
        byte_size=path.stat().st_size,
        mimetype="audio/wav",
        filename="recording.wav",
    )
    recording.cache_duration(sum(durations))
    return tuple(spooled), recording, tuple(durations)


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()
