# MIT License

import asyncio
import math
import tempfile
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from eneo.files.text import MimeTypesBase

# FFmpeg owns both decoding and encoding. Keep native codec updates in the
# runtime package inventory instead of a second, wheel-bundled libsndfile.
_CONVERSION_TIMEOUT_SECONDS = 300
_INPUT_FORMATS = "mov,mp3,wav,ogg,matroska,webm"


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


async def _run_codec(
    executable: Literal["ffmpeg", "ffprobe"], *arguments: str
) -> bytes:
    process = await asyncio.create_subprocess_exec(
        executable,
        *(["-nostdin"] if executable == "ffmpeg" else []),
        "-hide_banner",
        "-loglevel",
        "error",
        "-threads",
        "1",
        *arguments,
        stdin=asyncio.subprocess.DEVNULL,
        # Only ffprobe's single duration value uses stdout; encoders write files.
        stdout=asyncio.subprocess.PIPE,
        # Media metadata and decoder messages can contain uploaded content.
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(_CONVERSION_TIMEOUT_SECONDS):
            stdout, _ = await process.communicate()
        if process.returncode:
            raise ValueError("Audio conversion failed: invalid or unsupported audio")
        return stdout
    finally:
        # Reap the decoder before deleting its files, also on cancellation or
        # timeout. A cancelled upload must not leave a converter running.
        if process.returncode is None:
            process.kill()
            await process.wait()


@asynccontextmanager
async def to_wav(filepath: str) -> AsyncGenerator["AudioFile"]:
    with tempfile.TemporaryDirectory(prefix="eneo-audio-") as directory:
        output = Path(directory) / "decoded.wav"
        await _run_codec(
            "ffmpeg",
            # An upload is a local media file, never a playlist or network URL.
            "-protocol_whitelist",
            "file",
            "-format_whitelist",
            _INPUT_FORMATS,
            "-i",
            str(Path(filepath).resolve()),
            "-map",
            "0:a:0",
            "-vn",
            "-sn",
            "-dn",
            "-map_metadata",
            "-1",
            "-c:a",
            "pcm_s16le",
            str(output),
        )
        # Python 3.11's wave reader cannot read WAVE_FORMAT_EXTENSIBLE (valid
        # high-rate/multichannel PCM). Use the same codec owner for its metadata.
        duration = float(
            await _run_codec(
                "ffprobe",
                "-protocol_whitelist",
                "file",
                "-f",
                "wav",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(output),
            )
        )
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Audio contains no samples")
        yield AudioFile(str(output), duration)


class AudioFile:
    """Decoded PCM WAV owned by ``to_wav`` for one transcription."""

    def __init__(self, path_to_file: str, duration: float):
        self.path = Path(path_to_file)
        self._duration = duration

    @property
    def duration(self) -> float:
        return self._duration

    @asynccontextmanager
    async def asplit_file(self, seconds: int) -> AsyncGenerator[list[Path]]:
        if seconds <= 0:
            raise ValueError("Audio segment duration must be positive")
        with tempfile.TemporaryDirectory(prefix="eneo-audio-segments-") as directory:
            await _run_codec(
                "ffmpeg",
                "-protocol_whitelist",
                "file",
                "-f",
                "wav",
                "-i",
                str(self.path.resolve()),
                "-map",
                "0:a:0",
                "-ac",
                "1",
                "-c:a",
                "libmp3lame",
                "-f",
                "segment",
                "-segment_time",
                str(seconds),
                "-reset_timestamps",
                "1",
                str(Path(directory) / "%08d.mp3"),
            )
            files = sorted(Path(directory).glob("*.mp3"))
            if not files:
                raise ValueError("Audio contains no samples")
            yield files

    def delete(self) -> None:
        self.path.unlink()
