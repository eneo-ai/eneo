import asyncio
import threading
import warnings
import wave
from contextlib import contextmanager

import numpy as np
import pytest
import soundfile as sf

from eneo.files import audio


@pytest.fixture
def recording(tmp_path, monkeypatch):
    # audioread imports deprecated Python 3.11 decoders while discovering backends.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        audio.audioread.available_backends()
    assert all(
        warning.category is DeprecationWarning
        and str(warning.message).startswith(("'aifc'", "'audioop'", "'sunau'"))
        for warning in caught
    )
    source = tmp_path / "source.wav"
    samples = (np.arange(80000, dtype=np.int32) % 30000).astype(np.int16)
    with wave.open(str(source), "wb") as handle:
        handle.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        handle.writeframes(samples.tobytes())
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    monkeypatch.setattr(audio.tempfile, "tempdir", str(temp_dir))
    return source, samples, temp_dir


@pytest.mark.parametrize(
    ("duration", "byte_limit", "limit", "ceiling"),
    [(1, 1_000_000, "duration_seconds", 1), (100, 6000, "decoded_bytes", 6000)],
)
async def test_decode_stops_before_writing_the_exceeded_bound(
    recording, monkeypatch, duration, byte_limit, limit, ceiling
):
    source, samples, temp_dir = recording
    written = []
    writeframes = wave.Wave_write.writeframes

    def record_write(handle, data):
        written.append(len(data))
        return writeframes(handle, data)

    monkeypatch.setattr(wave.Wave_write, "writeframes", record_write)
    limits = audio.AudioDecodeLimits(duration, byte_limit)
    with pytest.raises(audio.AudioDecodeLimitExceeded) as error:
        async with audio.to_wav(str(source), limits=limits):
            pytest.fail("An oversized recording must not reach the consumer")

    assert error.value.limit == limit
    assert error.value.measured > ceiling
    assert error.value.ceiling == ceiling
    assert sum(written) < samples.nbytes
    assert sum(written) <= min(duration * 8000 * 2, byte_limit)
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


async def test_cancel_during_decode_joins_worker_before_cleanup(recording, monkeypatch):
    source, _, temp_dir = recording
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    audio_open = audio.audioread.audio_open

    @contextmanager
    def blocked_open(path):
        with audio_open(path) as handle:
            loop.call_soon_threadsafe(started.set)
            assert release.wait(timeout=5)
            yield handle

    monkeypatch.setattr(audio.audioread, "audio_open", blocked_open)

    async def consume():
        async with audio.to_wav(str(source)):
            pytest.fail("Cancelled decoding must not yield a file")

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert list(temp_dir.iterdir()) == []
