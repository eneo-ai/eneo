# MIT License

import asyncio
import math
import tempfile
import threading
import wave
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Generator
from contextlib import (
    AbstractContextManager,
    aclosing,
    asynccontextmanager,
    closing,
    suppress,
)
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import IO, Literal, TypeVar, cast

import audioread
import numpy as np
import soundfile as sf
from soundfile import SoundFile

from eneo.files.text import MimeTypesBase
from eneo.main.config import get_settings
from eneo.main.exceptions import FileTooLargeException
from eneo.main.logging import get_logger

logger = get_logger(__name__)

FRAMES = 32768  # Number of frames in one mebibyte

# Concrete numpy array type used throughout this module.
# soundfile.blocks() yields float64 arrays; we use this alias for clarity.
_FloatArray = np.ndarray[tuple[int, ...], np.dtype[np.float64]]


# TODO: When we support video, remove the video mimetypes
class AudioMimeTypes(MimeTypesBase):
    M4A = "audio/x-m4a"
    OGG = "audio/ogg"
    WAV = "audio/wav"
    MPEG = "audio/mpeg"
    MP3 = "audio/mp3"
    WEBM = "video/webm"  # Same container as for video
    MP4 = "video/mp4"  # Same container as for video
    WEBA = "audio/webm"
    MP4A = "audio/mp4"


@dataclass(frozen=True, slots=True)
class AudioDecodeLimits:
    max_duration_seconds: float
    max_decoded_bytes: int

    @classmethod
    def from_settings(cls) -> "AudioDecodeLimits":
        settings = get_settings()
        return cls(
            max_duration_seconds=settings.flow_audio_max_duration_seconds,
            max_decoded_bytes=settings.flow_audio_max_decoded_bytes,
        )


class AudioDecodeLimitExceeded(FileTooLargeException):
    def __init__(
        self,
        *,
        limit: Literal["duration_seconds", "decoded_bytes"],
        measured: float,
        ceiling: float,
    ) -> None:
        self.limit = limit
        self.measured = measured
        self.ceiling = ceiling
        super().__init__(
            f"Audio decode limit exceeded: {limit} ({measured:g} > {ceiling:g}).",
            code="audio_exceeds_limit",
            context={
                "limit": limit,
                "measured": math.ceil(measured),
                "ceiling": math.ceil(ceiling),
            },
            limit_name=f"flow_audio_max_{limit}",
        )


_T = TypeVar("_T")


async def _run_audio_worker(work: Callable[[], _T], stop: threading.Event) -> _T:
    worker = asyncio.create_task(asyncio.to_thread(work))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        stop.set()
        # A running thread must finish before its files or generator are closed.
        # Further cancellation must not interrupt that ownership handoff.
        while not worker.done():
            with suppress(asyncio.CancelledError, Exception):
                await asyncio.shield(worker)
        if not worker.cancelled():
            worker.exception()
        raise


def _to_wav(
    filepath: str,
    target: IO[bytes],
    *,
    limits: AudioDecodeLimits,
    stop: threading.Event,
) -> None:
    logger.debug(f"Converting {filepath} to wav")

    with audioread.audio_open(filepath) as f:
        samplerate = f.samplerate
        channels = f.channels
        bytes_per_second = samplerate * channels * 2
        duration_bytes = limits.max_duration_seconds * bytes_per_second
        decoded_bytes = 0
        with wave.open(target, "w") as of:
            of.setframerate(samplerate)
            of.setnchannels(channels)
            of.setsampwidth(2)

            for buf in f:
                if stop.is_set():
                    return
                next_bytes = decoded_bytes + len(buf)
                if next_bytes > min(duration_bytes, limits.max_decoded_bytes):
                    if duration_bytes <= limits.max_decoded_bytes:
                        raise AudioDecodeLimitExceeded(
                            limit="duration_seconds",
                            measured=next_bytes / bytes_per_second,
                            ceiling=limits.max_duration_seconds,
                        )
                    raise AudioDecodeLimitExceeded(
                        limit="decoded_bytes",
                        measured=next_bytes,
                        ceiling=limits.max_decoded_bytes,
                    )
                of.writeframes(buf)
                decoded_bytes = next_bytes


@asynccontextmanager
async def to_wav(
    filepath: str, *, limits: AudioDecodeLimits | None = None
) -> AsyncGenerator["AudioFile", None]:
    stop = threading.Event()
    tmp_file = tempfile.NamedTemporaryFile(suffix=".wav")
    try:
        await _run_audio_worker(
            partial(
                _to_wav,
                filepath,
                tmp_file,
                limits=limits or AudioDecodeLimits.from_settings(),
                stop=stop,
            ),
            stop,
        )
        tmp_file.flush()
        yield AudioFile(tmp_file.name)
    finally:
        stop.set()
        tmp_file.close()


class AudioFile:
    def __init__(self, path_to_file: str):
        super().__init__()
        self.path = Path(path_to_file)
        # sf.info() returns _SoundFileInfo which lacks annotations; we store it
        # and access .samplerate/.channels as int at call sites with explicit casts.
        self._info = sf.info(path_to_file)  # pyright: ignore[reportUnknownMemberType]  # soundfile lacks stubs for info()
        self._samplerate: int = self._info.samplerate  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]  # soundfile lacks stubs
        self._channels: int = self._info.channels  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]  # soundfile lacks stubs
        self._duration: float = float(self._info.duration)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]  # soundfile lacks stubs

    @property
    def duration(self) -> float:
        """Total duration of the audio file in seconds."""
        return self._duration

    def _iter_chunks(
        self, seconds: int, *, stop: threading.Event | None = None
    ) -> Generator[IO[bytes], None, None]:
        if seconds <= 0:
            raise ValueError("Chunk duration must be positive")
        stop = stop or threading.Event()
        max_frames = self._samplerate * seconds
        blocks = cast(
            Generator[_FloatArray, None, None], sf.blocks(self.path, blocksize=FRAMES)
        )
        with closing(blocks):
            pending = next(blocks, None)
            while pending is not None and not stop.is_set():
                with tempfile.NamedTemporaryFile(suffix=".mp3") as temp_file:
                    writer = cast(
                        AbstractContextManager[SoundFile],
                        SoundFile(
                            temp_file,
                            mode="w",
                            samplerate=self._samplerate,
                            channels=1,
                            format="mp3",
                        ),
                    )
                    with writer as chunk:
                        frames_in_chunk = 0
                        while pending is not None and frames_in_chunk < max_frames:
                            if stop.is_set():
                                return
                            room = max_frames - frames_in_chunk
                            data = pending[:room]
                            rest = pending[room:]
                            pending = rest if len(rest) else None
                            if self._channels == 2:
                                data = np.mean(data, axis=1)
                            chunk.write(data)
                            frames_in_chunk += len(data)
                            if pending is None and frames_in_chunk < max_frames:
                                pending = next(blocks, None)
                    temp_file.flush()
                    yield temp_file
                if pending is None:
                    pending = next(blocks, None)

    @asynccontextmanager
    async def asplit_file(
        self, seconds: int
    ) -> AsyncGenerator[AsyncIterator[Path], None]:
        logger.debug("Splitting the file")
        stop = threading.Event()
        chunks = self._iter_chunks(seconds, stop=stop)

        async def paths() -> AsyncGenerator[Path, None]:
            while True:
                temp_file = await _run_audio_worker(partial(next, chunks, None), stop)
                if temp_file is None:
                    return
                yield Path(temp_file.name)

        try:
            async with aclosing(paths()) as iterator:
                yield iterator
        finally:
            stop.set()
            chunks.close()

    def delete(self) -> None:
        self.path.unlink()
