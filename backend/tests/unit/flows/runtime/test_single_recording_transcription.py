from __future__ import annotations

import io
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.files import audio
from eneo.files.transcriber import TranscribedAudio
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.runtime.transcription import transcribe_audio_input
from eneo.main.config import get_settings
from eneo.main.exceptions import TypedIOValidationException
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    TranscriptSegment,
    TranscriptWord,
)
from tests.unit.files import test_audio
from tests.unittests.flows import audio_spool_test_support

spool_contract = audio_spool_test_support.spool_contract
ffmpeg = test_audio.ffmpeg


def _wav(seconds: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        handle.writeframes(b"\x00\x00" * 16000 * seconds)
    return buffer.getvalue()


def _part(name: str, seconds: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(), name=name, mimetype="audio/wav", blob=_wav(seconds)
    )


def _said(text: str, start: float, end: float, speaker: str) -> TranscriptSegment:
    return TranscriptSegment(
        text, start, end, speaker, (TranscriptWord(text, start, end),)
    )


# Anna speaks in both parts of a 20 s recording; Erik only in the first.
LABELLED = TranscribedAudio(
    text="",
    duration_seconds=20.0,
    transcript_segments=(
        _said("Hej.", 1.0, 2.0, "SPEAKER_07"),
        _said("Tack.", 4.0, 5.0, "SPEAKER_03"),
        _said("Punkt två.", 12.0, 13.0, "SPEAKER_07"),
    ),
    diarization="external",
    alignment="forced",
)


def _engine(labelled: TranscribedAudio = LABELLED) -> SimpleNamespace:
    return SimpleNamespace(
        transcribe=AsyncMock(
            side_effect=lambda *_, **__: TranscribedAudio(
                "[00:00:00 - 00:00:01] SPEAKER_00: Hej.", 10.0, diarization="external"
            )
        ),
        transcribe_recording=AsyncMock(return_value=labelled),
    )


async def _run(
    spool_contract, files, transcriber, *, single_recording=True, diarize=True
):
    return await transcribe_audio_input(
        files=files,
        transcriber=transcriber,
        transcription_model=SimpleNamespace(id=uuid4(), name="whisper-1"),
        language="sv",
        step_order=1,
        max_files=5,
        max_inline_text_bytes=100_000,
        open_audio_download=spool_contract.downloads(files),
        diarize=diarize,
        max_speakers=3,
        single_recording=single_recording,
    )


async def test_one_voice_keeps_one_label_across_the_parts(spool_contract, ffmpeg):
    files = [_part("del-1.wav", 10), _part("del-2.wav", 10)]
    engine = _engine()

    result = await _run(spool_contract, files, engine)

    engine.transcribe.assert_not_awaited()
    engine.transcribe_recording.assert_awaited_once()
    recording = engine.transcribe_recording.await_args.args[0]
    assert [bound.duration for bound in recording.bounds] == [10.0, 10.0]
    assert recording.file_ids == tuple(file.id for file in files)
    assert engine.transcribe_recording.await_args.kwargs["max_speakers"] == 3

    stored = result.source.segments
    assert [(s["file_index"], s["start"], s["speaker"]) for s in stored] == [
        (0, 1.0, "SPEAKER_00"),
        (0, 4.0, "SPEAKER_01"),
        (1, 2.0, "SPEAKER_00"),
    ]
    assert [
        (e["label"], e["file_index"], e["line_count"]) for e in result.speakers
    ] == [
        ("SPEAKER_00", 0, 2),
        ("SPEAKER_01", 0, 1),
    ]
    assert result.audio_seconds == 20.0
    assert result.diarization == "external"
    spool_contract.assert_finished()


@pytest.mark.parametrize(
    ("single_recording", "diarize"), [(False, True), (True, False)]
)
async def test_unmarked_or_unlabelled_parts_keep_the_per_file_path(
    spool_contract, ffmpeg, single_recording, diarize
):
    files = [_part("a.wav", 1), _part("b.wav", 1)]
    engine = _engine()

    await _run(
        spool_contract,
        files,
        engine,
        single_recording=single_recording,
        diarize=diarize,
    )

    engine.transcribe_recording.assert_not_awaited()
    assert engine.transcribe.await_count == 2


async def test_an_engine_that_labels_no_speakers_keeps_the_per_file_path(
    spool_contract, ffmpeg
):
    files = [_part("a.wav", 1), _part("b.wav", 1)]
    registry = SimpleNamespace(
        transcribe=AsyncMock(return_value=TranscribedAudio("Hej.", 1.0))
    )

    result = await _run(spool_contract, files, registry)

    assert registry.transcribe.await_count == 2
    assert "Hej." in result.text


async def test_the_audio_limit_covers_the_whole_recording_before_any_engine_call(
    spool_contract, ffmpeg, monkeypatch
):
    settings = get_settings().model_copy(update={"flow_audio_max_duration_seconds": 15})
    monkeypatch.setattr(audio, "get_settings", lambda: settings)
    files = [_part("del-1.wav", 10), _part("del-2.wav", 10)]
    engine = _engine()

    with pytest.raises(TypedIOValidationException) as refused:
        await _run(spool_contract, files, engine)

    assert refused.value.code == FlowApiErrorCode.TYPED_IO_AUDIO_EXCEEDS_LIMIT.value
    engine.transcribe_recording.assert_not_awaited()
    spool_contract.assert_finished()


async def test_no_later_part_is_downloaded_once_the_recording_is_over_the_limit(
    spool_contract, ffmpeg, monkeypatch
):
    settings = get_settings().model_copy(update={"flow_audio_max_duration_seconds": 15})
    monkeypatch.setattr(audio, "get_settings", lambda: settings)
    files = [_part("del-1.wav", 10), _part("del-2.wav", 10), _part("del-3.wav", 10)]
    downloads = spool_contract.downloads(files)

    with pytest.raises(TypedIOValidationException):
        await transcribe_audio_input(
            files=files,
            transcriber=_engine(),
            transcription_model=SimpleNamespace(id=uuid4(), name="whisper-1"),
            language="sv",
            step_order=1,
            max_files=5,
            max_inline_text_bytes=100_000,
            open_audio_download=downloads,
            diarize=True,
            single_recording=True,
        )

    assert downloads.calls == [files[0].id, files[1].id]
    spool_contract.assert_finished()


async def test_a_result_that_cannot_return_to_its_parts_fails_the_step(
    spool_contract, ffmpeg
):
    wordless_across = TranscribedAudio(
        text="",
        duration_seconds=20.0,
        transcript_segments=(
            TranscriptSegment("Över skarven.", 9.0, 12.0, "SPEAKER_00"),
        ),
        diarization="external",
    )
    files = [_part("del-1.wav", 10), _part("del-2.wav", 10)]

    with pytest.raises(Exception) as failed:
        await _run(spool_contract, files, _engine(wordless_across))

    assert failed.value.code == FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_FAILED.value
    spool_contract.assert_finished()
