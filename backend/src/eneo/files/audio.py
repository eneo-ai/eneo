# MIT License

import asyncio
import math
import tempfile
import threading
import wave
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Callable,
    Generator,
)
from contextlib import (
    AbstractContextManager,
    aclosing,
    asynccontextmanager,
    closing,
    contextmanager,
    suppress,
)
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import IO, Literal, TypeVar, cast

import numpy as np
import soundfile as sf
from soundfile import SoundFile

from eneo.files.text import MimeTypesBase
from eneo.main.config import Settings, get_settings
from eneo.main.exceptions import FileTooLargeException
from eneo.main.logging import get_logger

logger = get_logger(__name__)

FRAMES = 32768  # Number of frames in one mebibyte

_DECODE_SAMPLE_RATE = 16000
_DECODE_CHANNELS = 1
_DECODE_SAMPLE_WIDTH = 2
_DECODE_BYTES_PER_SECOND = _DECODE_SAMPLE_RATE * _DECODE_CHANNELS * _DECODE_SAMPLE_WIDTH
_DECODE_BLOCK_BYTES = 64 * 1024
_DECODER_TERMINATE_GRACE_SECONDS = 0.5

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
    def from_settings(cls, settings: Settings | None = None) -> "AudioDecodeLimits":
        settings = settings or get_settings()
        return cls(
            max_duration_seconds=settings.flow_audio_max_duration_seconds,
            max_decoded_bytes=settings.flow_audio_max_decoded_bytes,
        )

    @property
    def longest_audio_seconds(self) -> int:
        """Whole seconds of audio one decode accepts: the tighter of both ceilings."""
        return int(
            min(
                self.max_duration_seconds,
                self.max_decoded_bytes / _DECODE_BYTES_PER_SECOND,
            )
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


async def _read_decoded_audio(
    process: asyncio.subprocess.Process,
    *,
    limits: AudioDecodeLimits,
    writer: wave.Wave_write | None,
    decoded_before: int,
) -> float:
    stdout = cast(asyncio.StreamReader, process.stdout)
    pending = b""
    decoded_bytes = decoded_before
    duration_bytes = limits.max_duration_seconds * _DECODE_BYTES_PER_SECOND
    while data := await stdout.read(_DECODE_BLOCK_BYTES):
        next_bytes = decoded_bytes + len(data)
        if next_bytes > min(duration_bytes, limits.max_decoded_bytes):
            if duration_bytes <= limits.max_decoded_bytes:
                raise AudioDecodeLimitExceeded(
                    limit="duration_seconds",
                    measured=next_bytes / _DECODE_BYTES_PER_SECOND,
                    ceiling=limits.max_duration_seconds,
                )
            raise AudioDecodeLimitExceeded(
                limit="decoded_bytes",
                measured=next_bytes,
                ceiling=limits.max_decoded_bytes,
            )
        data = pending + data
        complete = len(data) - len(data) % _DECODE_SAMPLE_WIDTH
        if writer is not None:
            writer.writeframesraw(memoryview(data)[:complete])
        pending = data[complete:]
        decoded_bytes = next_bytes
    returncode = await process.wait()
    if returncode != 0:
        raise ValueError(f"Audio decoder exited with status {returncode}")
    if pending:
        raise ValueError("Audio decoder returned an incomplete PCM frame")
    return (decoded_bytes - decoded_before) / _DECODE_BYTES_PER_SECOND


async def _terminate_decoder(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        with suppress(ProcessLookupError):
            process.terminate()

    async def drain_and_wait() -> None:
        # A paused stdout transport can prevent wait() from completing even
        # after the child exits. Discard its remaining output in bounded reads.
        if process.stdout is not None:
            while await process.stdout.read(_DECODE_BLOCK_BYTES):
                pass
        await process.wait()

    waiter = asyncio.create_task(drain_and_wait())
    try:
        await asyncio.wait_for(
            asyncio.shield(waiter), timeout=_DECODER_TERMINATE_GRACE_SECONDS
        )
    except TimeoutError:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        await waiter


async def _decode_audio(
    filepath: str,
    *,
    limits: AudioDecodeLimits,
    writer: wave.Wave_write | None = None,
    decoded_before: int = 0,
) -> float:
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        filepath,
        "-f",
        "s16le",
        "-ac",
        str(_DECODE_CHANNELS),
        "-ar",
        str(_DECODE_SAMPLE_RATE),
        "pipe:1",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        limit=_DECODE_BLOCK_BYTES,
    )
    try:
        return await _read_decoded_audio(
            process, limits=limits, writer=writer, decoded_before=decoded_before
        )
    finally:
        cleanup = asyncio.create_task(_terminate_decoder(process))
        cancelled = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
        cleanup.result()
        if cancelled:
            raise asyncio.CancelledError


class JoinedWav:
    """Files decoded in order into one WAV under one budget: the limits bound
    the joined audio, not each file."""

    def __init__(self, writer: wave.Wave_write, limits: AudioDecodeLimits) -> None:
        self._writer = writer
        self._limits = limits
        self._decoded = 0

    async def append(self, filepath: str) -> float:
        """Decode one more file onto the end; returns its decoded length."""
        seconds = await _decode_audio(
            filepath,
            limits=self._limits,
            writer=self._writer,
            decoded_before=self._decoded,
        )
        self._decoded += round(seconds * _DECODE_BYTES_PER_SECOND)
        return seconds


@contextmanager
def joined_wav(target: IO[bytes], *, limits: AudioDecodeLimits) -> Generator[JoinedWav]:
    with wave.open(target, "w") as writer:
        writer.setframerate(_DECODE_SAMPLE_RATE)
        writer.setnchannels(_DECODE_CHANNELS)
        writer.setsampwidth(_DECODE_SAMPLE_WIDTH)
        yield JoinedWav(writer, limits)


async def measure_duration(
    filepath: str, *, limits: AudioDecodeLimits | None = None
) -> float:
    return await _decode_audio(
        filepath, limits=limits or AudioDecodeLimits.from_settings()
    )


@asynccontextmanager
async def to_wav(
    filepath: str, *, limits: AudioDecodeLimits | None = None
) -> AsyncGenerator["AudioFile", None]:
    tmp_file = tempfile.NamedTemporaryFile(suffix=".wav")
    try:
        with joined_wav(
            tmp_file, limits=limits or AudioDecodeLimits.from_settings()
        ) as joined:
            await joined.append(filepath)
        tmp_file.flush()
        yield AudioFile(tmp_file.name)
    finally:
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
