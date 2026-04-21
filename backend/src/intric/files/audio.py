# MIT License

import asyncio
import tempfile
import wave
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import IO

import audioread
import numpy as np
import soundfile as sf
from soundfile import SoundFile

from intric.files.text import MimeTypesBase
from intric.main.logging import get_logger

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


def _to_wav(filepath: str) -> IO[bytes]:
    logger.debug(f"Converting {filepath} to wav")

    with audioread.audio_open(filepath) as f:  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]  # audioread lacks stubs
        # audioread has no type stubs; cast via int()/bytes() to give pyright concrete types
        # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType] — audioread lacks stubs
        samplerate = int(f.samplerate)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]  # audioread lacks stubs
        channels = int(f.channels)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]  # audioread lacks stubs
        tmp_file = tempfile.NamedTemporaryFile(suffix=".wav")
        with wave.open(tmp_file, "w") as of:
            of.setframerate(samplerate)
            of.setnchannels(channels)
            of.setsampwidth(2)

            for buf in f:  # pyright: ignore[reportUnknownVariableType]  # audioread yields bytes at runtime
                buf_bytes: bytes = bytes(buf)  # pyright: ignore[reportUnknownArgumentType]  # audioread yields bytes at runtime
                of.writeframes(buf_bytes)

    return tmp_file


@asynccontextmanager
async def to_wav(filepath: str) -> AsyncIterator["AudioFile"]:
    tmp_file = await asyncio.to_thread(_to_wav, filepath)

    try:
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

    def _gen_file(self) -> Generator[_FloatArray, None, None]:
        # sf.blocks() yields ndarray[Any, dtype[float64]]; the cast is safe.
        for block in sf.blocks(self.path, blocksize=FRAMES):  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]  # soundfile lacks stubs
            yield block  # pyright: ignore[reportUnknownVariableType]  # soundfile lacks stubs

    def _write_to_file(
        self, gen: Generator[_FloatArray, None, None], max_size: int
    ) -> tuple[IO[bytes], bool]:
        frames_in_file = 0
        temp_file = tempfile.NamedTemporaryFile(suffix=".mp3")
        soundfile = SoundFile(
            temp_file,
            mode="w",
            samplerate=self._samplerate,
            channels=1,
            format="mp3",
        )
        for block in gen:  # pyright: ignore[reportUnknownVariableType]  # _gen_file yield is partially unknown due to soundfile stubs
            if self._channels == 2:
                # Make mono by averaging the two channels
                data: _FloatArray = np.sum(block, axis=1) / 2  # pyright: ignore[reportUnknownArgumentType]  # block type from soundfile lacks stubs
            else:
                data = block  # pyright: ignore[reportUnknownVariableType]  # soundfile stubs propagate unknown

            frames_in_file += len(data)
            soundfile.write(data)  # pyright: ignore[reportUnknownMemberType]  # soundfile lacks stubs
            soundfile.flush()  # pyright: ignore[reportUnknownMemberType]  # soundfile lacks stubs

            if frames_in_file > max_size:
                return temp_file, False

        return temp_file, True

    def _split_file(self, seconds: int) -> list[IO[bytes]]:
        max_size = self._samplerate * seconds
        temp_files: list[IO[bytes]] = []
        gen = self._gen_file()
        done = False
        while not done:
            file, done = self._write_to_file(gen, max_size)
            temp_files.append(file)

        return temp_files

    @asynccontextmanager
    async def asplit_file(self, seconds: int) -> AsyncIterator[list[Path]]:
        logger.debug("Splitting the file")

        temp_files = await asyncio.to_thread(self._split_file, seconds)
        filepaths = [Path(f.name) for f in temp_files]

        logger.debug("File was split in %s parts", len(filepaths))

        try:
            yield filepaths
        finally:
            for f in temp_files:
                f.close()

    def delete(self) -> None:
        self.path.unlink()
