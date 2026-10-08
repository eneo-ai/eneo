"""Real decoder contracts, also run directly in the production image without pytest."""

import asyncio
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from eneo.files import audio


class AudioProcessLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_conversion_reaps_process_and_removes_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "ffmpeg"
            pidfile = root / "pid"
            executable.write_text(
                f"#!{sys.executable}\n"
                "import os, pathlib, sys, time\n"
                f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()))\n"
                "pathlib.Path(sys.argv[-1]).write_bytes(b'partial')\n"
                "time.sleep(30)\n"
            )
            executable.chmod(0o755)
            with (
                patch.dict(os.environ, {"PATH": str(root)}),
                patch.object(tempfile, "tempdir", directory),
            ):
                task = asyncio.create_task(self._convert(str(root / "input.wav")))
                async with asyncio.timeout(5):
                    while not pidfile.exists():
                        await asyncio.sleep(0.01)
                pid = int(pidfile.read_text())
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
                self.assertEqual(list(root.glob("eneo-audio-*")), [])

    @staticmethod
    async def _convert(path: str):
        async with audio.to_wav(path):
            pass


@unittest.skipUnless(
    shutil.which("ffmpeg"), "FFmpeg required; mandatory in image check"
)
class AudioFormatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "stereo.wav"
        with wave.open(str(self.source), "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(32000)
            output.writeframes(
                b"".join(
                    struct.pack("<hh", sample, sample)
                    for sample in (
                        int(8000 * math.sin(i * 2 * math.pi * 440 / 32000))
                        for i in range(40000)
                    )
                )
            )

    async def test_supported_formats_decode_and_split_into_mono_mp3(self):
        # Match audio.py / extensions.py, including aliases MP2, Opus and Speex.
        for extension, codec in [
            ("wav", "pcm_s16le"),
            ("mp3", "libmp3lame"),
            ("mp2", "mp2"),
            ("m4a", "aac"),
            ("m4a", "alac"),
            ("ogg", "libvorbis"),
            ("opus", "libopus"),
            ("spx", "libspeex"),
            ("mp4", "aac"),
            ("webm", "libopus"),
        ]:
            with self.subTest(extension=extension, codec=codec):
                encoded = self.root / f"{codec}.{extension}"
                subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-threads",
                        "1",
                        "-i",
                        str(self.source),
                        "-c:a",
                        codec,
                        str(encoded),
                    ],
                    check=True,
                    timeout=15,
                    capture_output=True,
                )
                # Upload staging does not preserve the format's extension.
                staged = self.root / "upload.bin"
                shutil.copyfile(encoded, staged)
                async with audio.to_wav(str(staged)) as decoded:
                    self.assertAlmostEqual(decoded.duration, 1.25, delta=0.15)
                    wav_path = decoded.path
                    async with decoded.asplit_file(1) as segments:
                        self.assertEqual(len(segments), 2)
                        for segment in segments:
                            result = subprocess.run(
                                [
                                    "ffprobe",
                                    "-v",
                                    "error",
                                    "-show_entries",
                                    "stream=codec_name,channels:format=duration",
                                    "-of",
                                    "json",
                                    str(segment),
                                ],
                                check=True,
                                timeout=10,
                                capture_output=True,
                                text=True,
                            )
                            info = json.loads(result.stdout)
                            self.assertEqual(info["streams"][0]["codec_name"], "mp3")
                            self.assertEqual(info["streams"][0]["channels"], 1)
                            self.assertGreater(float(info["format"]["duration"]), 0)
                            self.assertLess(float(info["format"]["duration"]), 1.2)
                    self.assertTrue(all(not segment.exists() for segment in segments))
                self.assertFalse(wav_path.exists())

    async def test_malformed_media_and_playlists_fail_and_clean_up(self):
        for content in [
            b"not audio",
            b"RIFF\xff\xff\xff\xffWAVEfmt ",
            b"#EXTM3U\n#EXT-X-TARGETDURATION:1\nhttp://127.0.0.1/private\n",
            f"ffconcat version 1.0\nfile '{self.source}'\n".encode(),
        ]:
            with self.subTest(content=content[:16]):
                source = self.root / "untrusted.wav"
                source.write_bytes(content)
                with patch.object(tempfile, "tempdir", self.directory.name):
                    with self.assertRaises(ValueError):
                        async with audio.to_wav(str(source)):
                            self.fail("Invalid media was accepted")
                self.assertEqual(list(self.root.glob("eneo-audio-*")), [])

    async def test_high_rate_and_multichannel_pcm(self):
        for rate, channels in [(96000, 2), (48000, 6)]:
            with self.subTest(rate=rate, channels=channels):
                source = self.root / "extended.wav"
                with wave.open(str(source), "wb") as output:
                    output.setnchannels(channels)
                    output.setsampwidth(2)
                    output.setframerate(rate)
                    output.writeframes(b"\x01\x00" * rate * channels)
                async with audio.to_wav(str(source)) as decoded:
                    self.assertAlmostEqual(decoded.duration, 1, delta=0.01)
                    async with decoded.asplit_file(300) as segments:
                        self.assertEqual(len(segments), 1)
                        self.assertGreater(segments[0].stat().st_size, 0)

    async def test_invalid_segment_duration_is_rejected(self):
        async with audio.to_wav(str(self.source)) as decoded:
            for seconds in [0, -1]:
                with self.assertRaises(ValueError):
                    async with decoded.asplit_file(seconds):
                        self.fail("Invalid segment duration was accepted")


if __name__ == "__main__":
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("Image must include FFmpeg and ffprobe")
    unittest.main()
