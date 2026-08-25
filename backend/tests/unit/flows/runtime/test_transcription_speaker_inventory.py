from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from eneo.files.transcriber import TranscribedAudio
from eneo.flows.runtime.transcription import transcribe_audio_input

FILE_TEXT = "\n".join(
    [
        "[00:00:00 - 00:00:04] SPEAKER_00: Hej.",
        "[00:00:05 - 00:00:09] SPEAKER_01: Hallå.",
    ]
)


def _file(name: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), name=name, mimetype="audio/mpeg")


def _transcriber(*results: TranscribedAudio) -> SimpleNamespace:
    return SimpleNamespace(transcribe=AsyncMock(side_effect=list(results)))


async def _run(files, transcriber, max_speakers=None):
    return await transcribe_audio_input(
        max_speakers=max_speakers,
        files=files,
        transcriber=transcriber,
        transcription_model=SimpleNamespace(id=uuid4(), name="whisper-1"),
        language="sv",
        step_order=1,
        max_files=5,
        max_inline_text_bytes=100_000,
        load_audio_payload=AsyncMock(
            side_effect=lambda file_id: SimpleNamespace(id=file_id, blob=b"x")
        ),
    )


async def test_labels_are_unique_across_files_and_inventoried() -> None:
    files = [_file("a.mp3"), _file("b.mp3")]
    transcriber = _transcriber(
        TranscribedAudio(FILE_TEXT, 10.0, diarization="external"),
        TranscribedAudio(FILE_TEXT, 10.0, diarization="external"),
    )

    result = await _run(files, transcriber)

    assert "SPEAKER_02: Hej." in result.text and "SPEAKER_03: Hallå." in result.text
    assert result.text.count("SPEAKER_00: Hej.") == 1
    labels = [entry["label"] for entry in result.speakers]
    assert labels == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02", "SPEAKER_03"]
    assert [entry["file_index"] for entry in result.speakers] == [0, 0, 1, 1]
    assert result.speakers[2]["file_id"] == str(files[1].id)
    assert result.to_metadata()["speakers"] == result.speakers


async def test_step_reports_the_coarsest_alignment_across_files() -> None:
    transcriber = _transcriber(
        TranscribedAudio(FILE_TEXT, 10.0, diarization="external", alignment="forced"),
        TranscribedAudio(
            FILE_TEXT, 10.0, diarization="external", alignment="segment_only"
        ),
    )

    result = await _run([_file("a.mp3"), _file("b.mp3")], transcriber)

    assert result.alignment == "segment_only"
    assert result.to_metadata()["alignment"] == "segment_only"


async def test_speaker_bound_reaches_the_transcriber_and_metadata() -> None:
    transcriber = _transcriber(
        TranscribedAudio(FILE_TEXT, 10.0, diarization="external")
    )

    result = await _run([_file("a.mp3")], transcriber, max_speakers=2)

    assert transcriber.transcribe.await_args.kwargs["max_speakers"] == 2
    assert result.to_metadata()["max_speakers"] == 2


async def test_files_without_speaker_labels_add_nothing() -> None:
    transcriber = _transcriber(
        TranscribedAudio("Bara text.", 10.0, diarization=None),
        TranscribedAudio(FILE_TEXT, 10.0, diarization="external"),
    )

    result = await _run([_file("a.mp3"), _file("b.mp3")], transcriber)

    # The unlabelled file does not consume label numbers.
    assert "SPEAKER_00: Hej." in result.text
    assert [entry["label"] for entry in result.speakers] == ["SPEAKER_00", "SPEAKER_01"]
