from __future__ import annotations

import hashlib
import shutil
import wave

import pytest

from eneo.files.audio import AudioDecodeLimitExceeded, AudioDecodeLimits
from eneo.flows.runtime.audio_spool import SpooledAudio, spool_recording
from tests.unit.files import test_audio

recording = test_audio.recording
ffmpeg = test_audio.ffmpeg


def _part(source, tmp_path, name: str) -> SpooledAudio:
    path = tmp_path / name
    shutil.copy(source, path)
    return SpooledAudio(
        path=path,
        digest="0" * 64,
        byte_size=path.stat().st_size,
        mimetype="audio/wav",
        filename=name,
    )


async def _as_is(part: SpooledAudio) -> SpooledAudio:
    return part


async def test_parts_join_into_one_wav_with_each_parts_decoded_length(
    recording, ffmpeg, tmp_path
):
    source, _, _ = recording
    parts = [_part(source, tmp_path, "a.wav"), _part(source, tmp_path, "b.wav")]

    spooled, joined, durations = await spool_recording(parts, _as_is)
    try:
        assert spooled == tuple(parts)
        assert durations == (10.0, 10.0)
        with wave.open(str(joined.path)) as handle:
            assert handle.getframerate() == 16000
            assert handle.getnframes() / handle.getframerate() == 20.0
        assert joined.digest == hashlib.sha256(joined.path.read_bytes()).hexdigest()
        assert joined.byte_size == joined.path.stat().st_size
        assert joined.mimetype == "audio/wav"
        assert await joined.measure_duration() == 20.0
    finally:
        await joined.aclose()
    assert not joined.path.exists()


async def test_the_decode_limit_covers_the_whole_recording(recording, ffmpeg, tmp_path):
    source, _, temp_dir = recording
    parts = [_part(source, tmp_path, "a.wav"), _part(source, tmp_path, "b.wav")]
    limits = AudioDecodeLimits(max_duration_seconds=15, max_decoded_bytes=10**9)

    with pytest.raises(AudioDecodeLimitExceeded) as refused:
        await spool_recording(parts, _as_is, limits=limits)

    assert refused.value.limit == "duration_seconds"
    assert refused.value.ceiling == 15
    assert refused.value.measured > 15
    assert list(temp_dir.iterdir()) == []
    assert not any(part.path.exists() for part in parts)
