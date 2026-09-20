import asyncio
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import numpy as np
import pytest
import soundfile as sf

from eneo.files import audio


@pytest.fixture
def recording(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    samples = (np.arange(80000, dtype=np.int32) % 30000).astype(np.int16)
    with wave.open(str(source), "wb") as handle:
        handle.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        handle.writeframes(samples.tobytes())
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    monkeypatch.setattr(audio.tempfile, "tempdir", str(temp_dir))
    return source, samples, temp_dir


@pytest.fixture
def ffmpeg():
    if shutil.which("ffmpeg") is None:
        pytest.skip("FFmpeg is not installed")


@pytest.fixture
def decoder_process(tmp_path, monkeypatch):
    processes = []
    popen = subprocess.Popen
    ready = tmp_path / "decoder-ready"

    def start(script):
        command = tmp_path / "decoder.py"
        command.write_text(script)

        def spawn(args, **kwargs):
            process = popen([sys.executable, "-u", str(command), str(ready)], **kwargs)
            processes.append(process)
            return process

        monkeypatch.setattr(subprocess, "Popen", spawn)
        return processes, ready

    yield start
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)


@pytest.mark.parametrize(
    ("duration", "byte_limit", "limit", "ceiling"),
    [(1, 1_000_000, "duration_seconds", 1), (100, 6000, "decoded_bytes", 6000)],
)
async def test_decode_stops_before_writing_the_exceeded_bound(
    recording, ffmpeg, monkeypatch, duration, byte_limit, limit, ceiling
):
    source, samples, temp_dir = recording
    written = []
    writeframes = wave.Wave_write.writeframesraw

    def record_write(handle, data):
        written.append(len(data))
        return writeframes(handle, data)

    monkeypatch.setattr(wave.Wave_write, "writeframesraw", record_write)
    limits = audio.AudioDecodeLimits(duration, byte_limit)
    with pytest.raises(audio.AudioDecodeLimitExceeded) as error:
        async with audio.to_wav(str(source), limits=limits):
            pytest.fail("An oversized recording must not reach the consumer")

    assert error.value.limit == limit
    assert error.value.measured > ceiling
    assert error.value.ceiling == ceiling
    assert sum(written) < samples.nbytes
    assert sum(written) <= min(duration * 16000 * 2, byte_limit)
    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize(
    "seconds, lengths", [(3, [24000, 24000, 24000, 8000]), (5, [40000, 40000])]
)
async def test_chunks_are_lazy_exact_and_preserve_every_frame(
    recording, monkeypatch, seconds, lengths
):
    source, samples, temp_dir = recording
    written = []
    original_write = audio.SoundFile.write

    def record_write(handle, data):
        written.append(data.copy())
        return original_write(handle, data)

    monkeypatch.setattr(audio.SoundFile, "write", record_write)
    actual_lengths = []
    previous = None
    async with audio.AudioFile(str(source)).asplit_file(seconds) as paths:
        assert list(temp_dir.iterdir()) == []
        async for path in paths:
            assert previous is None or not previous.exists()
            assert list(temp_dir.iterdir()) == [path]
            actual_lengths.append(len(sf.read(path)[0]))
            assert sum(len(block) for block in written) == sum(actual_lengths)
            previous = path

    assert actual_lengths == lengths
    assert sum(actual_lengths) == len(samples)
    np.testing.assert_array_equal(np.concatenate(written), samples / 32768)
    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize("during_write", [False, True])
async def test_cancel_during_split_removes_all_chunks(
    recording, monkeypatch, during_write
):
    source, _, temp_dir = recording
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original_write = audio.SoundFile.write

    def blocked_write(handle, data):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=5)
        return original_write(handle, data)

    if during_write:
        monkeypatch.setattr(audio.SoundFile, "write", blocked_write)

    async def consume():
        async with audio.AudioFile(str(source)).asplit_file(3) as paths:
            async for path in paths:
                assert path.exists()
                started.set()
                await asyncio.Future()

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        await asyncio.sleep(0)
        if during_write:
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert list(temp_dir.iterdir()) == []


async def test_split_write_failure_removes_the_partial_chunk(recording, monkeypatch):
    source, _, temp_dir = recording

    def fail_write(handle, data):
        raise OSError("write failed")

    monkeypatch.setattr(audio.SoundFile, "write", fail_write)
    with pytest.raises(OSError, match="write failed"):
        async with audio.AudioFile(str(source)).asplit_file(3) as paths:
            await anext(paths)
    assert list(temp_dir.iterdir()) == []


async def test_decode_keeps_duration_and_cleans_up_after_consumer_cancellation(
    recording,
    ffmpeg,
):
    source, _, temp_dir = recording
    entered = asyncio.Event()

    async def consume():
        async with audio.to_wav(str(source)) as decoded:
            assert decoded.duration == 10
            assert decoded.path.exists()
            entered.set()
            await asyncio.Future()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize("emit_header", [False, True])
async def test_cancel_stalled_decoder_kills_and_reaps_before_file_cleanup(
    recording, decoder_process, emit_header
):
    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
    source, _, temp_dir = recording
    processes, ready = decoder_process(
        "import pathlib, signal, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "pathlib.Path(sys.argv[1]).touch()\n"
        + (
            "sys.stdout.buffer.write(b'RIFF' + bytes(40)); sys.stdout.flush()\n"
            if emit_header
            else ""
        )
        + "time.sleep(60)\n"
    )

    async def consume():
        async with audio.to_wav(str(source)):
            pytest.fail("Cancelled decoding must not yield a file")

    task = asyncio.create_task(consume())
    try:
        async with asyncio.timeout(2):
            while not ready.exists() and not task.done():
                await asyncio.sleep(0.01)
        assert ready.exists(), "The decode must be owned by a subprocess"
        started = time.monotonic()
        task.cancel()
        await asyncio.sleep(0.05)
        assert list(temp_dir.iterdir())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(task), timeout=2)
        assert time.monotonic() - started < 2
        assert processes[0].returncode == -signal.SIGKILL
        with pytest.raises(ProcessLookupError):
            os.kill(processes[0].pid, 0)
        assert list(temp_dir.iterdir()) == []
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
        await asyncio.gather(task, return_exceptions=True)


async def test_measure_duration_counts_pcm_without_creating_a_wav(
    recording, ffmpeg, monkeypatch
):
    source, _, temp_dir = recording

    def refuse_temp_file(*args, **kwargs):
        pytest.fail("Measuring decoded duration must not materialise a WAV")

    monkeypatch.setattr(audio.tempfile, "NamedTemporaryFile", refuse_temp_file)
    assert await audio.measure_duration(str(source)) == 10
    assert list(temp_dir.iterdir()) == []


async def test_compressed_audio_stops_before_eof_with_bounded_reads(
    recording, ffmpeg, monkeypatch
):
    source, _, temp_dir = recording
    compressed = source.with_suffix(".flac")
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-stream_loop",
            "59",
            "-i",
            str(source),
            str(compressed),
        ],
        check=True,
        timeout=10,
    )
    processes = []
    bytes_read = []
    read_sizes = []
    popen = subprocess.Popen

    def spawn(*args, **kwargs):
        process = popen(*args, **kwargs)
        stdout = process.stdout

        def readinto(buffer):
            read_sizes.append(len(buffer))
            count = stdout.readinto(buffer)
            bytes_read.append(count)
            return count

        def read(size):
            read_sizes.append(size)
            data = stdout.read(size)
            bytes_read.append(len(data))
            return data

        process.stdout = Mock(wraps=stdout)
        process.stdout.readinto.side_effect = readinto
        process.stdout.read.side_effect = read
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn)
    writeframes = wave.Wave_write.writeframesraw
    written = []

    def slow_write(handle, data):
        written.append(len(data))
        time.sleep(0.02)
        return writeframes(handle, data)

    monkeypatch.setattr(wave.Wave_write, "writeframesraw", slow_write)
    with pytest.raises(audio.AudioDecodeLimitExceeded) as error:
        async with audio.to_wav(
            str(compressed), limits=audio.AudioDecodeLimits(1000, 65536)
        ):
            pytest.fail("The compressed recording must exceed the ceiling")

    assert error.value.limit == "decoded_bytes"
    assert 0 < sum(written) <= 65536
    assert sum(bytes_read) <= 65536 + 65536
    assert sum(bytes_read) < 600 * 16000 * 2
    assert read_sizes and max(read_sizes) <= 65536
    assert len(processes) == 1
    assert processes[0].returncode < 0
    assert list(temp_dir.iterdir()) == []


async def test_decoder_protocol_preserves_partial_frames_and_fixed_format(
    recording, decoder_process
):
    source, _, temp_dir = recording
    processes, _ = decoder_process(
        "import os, time\n"
        "os.write(1, b'\\x01'); time.sleep(0.03)\n"
        "os.write(1, b'\\x02\\x03'); time.sleep(0.03)\n"
        "os.write(1, b'\\x04')\n"
    )
    async with audio.to_wav(str(source)) as decoded:
        assert processes[0].returncode == 0
        with wave.open(str(decoded.path), "rb") as handle:
            assert (
                handle.getnchannels(),
                handle.getframerate(),
                handle.getsampwidth(),
            ) == (1, 16000, 2)
            assert handle.getnframes() == 2
            assert handle.readframes(2) == b"\x01\x02\x03\x04"
        assert decoded.duration == 2 / 16000
    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize(
    "script, message",
    [
        (
            "import os; os.write(1, bytes(32000)); raise SystemExit(7)",
            "exited with status 7",
        ),
        ("import os; os.write(1, bytes(3))", "incomplete PCM frame"),
    ],
)
async def test_decoder_failure_removes_partial_wav(
    recording, decoder_process, script, message
):
    source, _, temp_dir = recording
    processes, _ = decoder_process(script)
    with pytest.raises(ValueError, match=message):
        async with audio.to_wav(str(source)):
            pytest.fail("An unsuccessful decode must not reach the consumer")
    assert processes[0].returncode is not None
    assert list(temp_dir.iterdir()) == []
