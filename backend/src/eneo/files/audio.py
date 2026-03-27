# MIT License

import asyncio
import tempfile
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Iterator

import audioread
import numpy as np
import soundfile as sf
from soundfile import SoundFile

from eneo.files.text import MimeTypesBase
from eneo.main.logging import get_logger

logger = get_logger(__name__)

FRAMES = 32768  # Number of frames in one mebibyte


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


def _to_wav(filepath: str):
    logger.debug(f"Converting {filepath} to wav")

    with audioread.audio_open(filepath) as f:
        tmp_file = tempfile.NamedTemporaryFile(suffix=".wav")
        with wave.open(tmp_file, "w") as of:
            of.setframerate(f.samplerate)
            of.setnchannels(f.channels)
            of.setsampwidth(2)

            for buf in f:
                of.writeframes(buf)

    return tmp_file


@asynccontextmanager
async def to_wav(filepath: str):
    tmp_file = await asyncio.to_thread(_to_wav, filepath)

    try:
        yield AudioFile(tmp_file.name)
    finally:
        tmp_file.close()


class AudioFile:
    def __init__(self, path_to_file: str):
        self.path = Path(path_to_file)
        self.info = sf.info(path_to_file)

    def _gen_file(self):
        for block in sf.blocks(self.path, blocksize=FRAMES):
            yield block

    def _write_to_file(self, gen: Iterator[np.ndarray], max_size: int):
        frames_in_file = 0
        temp_file = tempfile.NamedTemporaryFile(suffix=".mp3")
        soundfile = SoundFile(
            temp_file,
            mode="w",
            samplerate=self.info.samplerate,
            channels=1,
            format="mp3",
        )
        for block in gen:
            if self.info.channels == 2:
                # Make mono by averageing the two channels
                data = np.sum(block, axis=1) / 2
            else:
                data = block

            frames_in_file += len(data)
            soundfile.write(data)
            soundfile.flush()

            if frames_in_file > max_size:
                return temp_file, False

        return temp_file, True

    def _split_file(self, seconds: int):
        max_size = self.info.samplerate * seconds
        temp_files = []
        gen = self._gen_file()
        done = False
        while not done:
            file, done = self._write_to_file(gen, max_size)
            temp_files.append(file)

        return temp_files

    @asynccontextmanager
    async def asplit_file(self, seconds: int):
        logger.debug("Splitting the file")

        temp_files = await asyncio.to_thread(self._split_file, seconds)
        filepaths = [Path(f.name) for f in temp_files]

        logger.debug("File was split in %s parts", len(filepaths))

        try:
            yield filepaths
        finally:
            for f in temp_files:
                f.close()

    def delete(self):
        self.path.unlink()
