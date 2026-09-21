from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.files.transcriber import TranscribedAudio
from eneo.flows.api.flow_models import TranscriptSpeakerEditPublic
from eneo.flows.domain.transcript_corrections import (
    TranscriptSpeakerEdit,
    apply_to_rendered_transcript,
    validate_speaker_edits,
)
from eneo.flows.runtime import transcription
from eneo.flows.runtime.remote_transcription import _parse_result_segments
from eneo.flows.runtime.transcription import transcribe_audio_input
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    TranscriptSegment,
    TranscriptWord,
)
from tests.unittests.flows import audio_spool_test_support

spool_contract = audio_spool_test_support.spool_contract

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


async def _run(spool_contract, files, transcriber, max_speakers=None):
    return await transcribe_audio_input(
        max_speakers=max_speakers,
        files=files,
        transcriber=transcriber,
        transcription_model=SimpleNamespace(id=uuid4(), name="whisper-1"),
        language="sv",
        step_order=1,
        max_files=5,
        max_inline_text_bytes=100_000,
        open_audio_download=spool_contract.downloads(files),
    )


async def test_labels_are_unique_across_files_and_inventoried(spool_contract) -> None:
    files = [_file("a.mp3"), _file("b.mp3")]
    transcriber = _transcriber(
        TranscribedAudio(FILE_TEXT, 10.0, diarization="external"),
        TranscribedAudio(FILE_TEXT, 10.0, diarization="external"),
    )

    result = await _run(spool_contract, files, transcriber)

    assert "SPEAKER_02: Hej." in result.text and "SPEAKER_03: Hallå." in result.text
    assert result.text.count("SPEAKER_00: Hej.") == 1
    labels = [entry["label"] for entry in result.speakers]
    assert labels == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02", "SPEAKER_03"]
    assert [entry["file_index"] for entry in result.speakers] == [0, 0, 1, 1]
    assert result.speakers[2]["file_id"] == str(files[1].id)
    assert result.to_metadata()["speakers"] == result.speakers


async def test_step_is_forced_only_when_every_file_was_forced(spool_contract) -> None:
    transcriber = _transcriber(
        TranscribedAudio(FILE_TEXT, 10.0, diarization="external", alignment="forced"),
        TranscribedAudio(
            FILE_TEXT, 10.0, diarization="external", alignment="segment_only"
        ),
    )

    result = await _run(spool_contract, [_file("a.mp3"), _file("b.mp3")], transcriber)

    assert result.alignment == "segment_only"
    assert result.to_metadata()["alignment"] == "segment_only"


async def test_speaker_bound_reaches_the_transcriber_and_metadata(
    spool_contract,
) -> None:
    transcriber = _transcriber(
        TranscribedAudio(FILE_TEXT, 10.0, diarization="external")
    )

    result = await _run(spool_contract, [_file("a.mp3")], transcriber, max_speakers=2)

    assert transcriber.transcribe.await_args.kwargs["max_speakers"] == 2
    assert result.to_metadata()["max_speakers"] == 2


async def test_files_without_speaker_labels_add_nothing(spool_contract) -> None:
    transcriber = _transcriber(
        TranscribedAudio("Bara text.", 10.0, diarization=None),
        TranscribedAudio(FILE_TEXT, 10.0, diarization="external"),
    )

    result = await _run(spool_contract, [_file("a.mp3"), _file("b.mp3")], transcriber)

    # The unlabelled file does not consume label numbers.
    assert "SPEAKER_00: Hej." in result.text
    assert [entry["label"] for entry in result.speakers] == ["SPEAKER_00", "SPEAKER_01"]


FILE_SEGMENTS = (
    TranscriptSegment("Hej.", 0.0, 4.004, speaker="SPEAKER_00"),
    TranscriptSegment("Hallå.", 5.0, 9.5, speaker="SPEAKER_01"),
)


async def test_segments_follow_the_text_labels_per_file(spool_contract) -> None:
    files = [_file("a.mp3"), _file("b.mp3")]
    transcriber = _transcriber(
        TranscribedAudio(
            FILE_TEXT, 10.0, diarization="external", transcript_segments=FILE_SEGMENTS
        ),
        TranscribedAudio(
            FILE_TEXT, 10.0, diarization="external", transcript_segments=FILE_SEGMENTS
        ),
    )

    result = await _run(spool_contract, files, transcriber)

    segments = result.to_metadata()["segments"]
    assert [segment["speaker"] for segment in segments] == [
        "SPEAKER_00",
        "SPEAKER_01",
        "SPEAKER_02",
        "SPEAKER_03",
    ]
    assert [segment["file_index"] for segment in segments] == [0, 0, 1, 1]
    # Preserve the precise service timeline in storage.
    assert segments[2] == {
        "file_index": 1,
        "start": 0.0,
        "end": 4.004,
        "speaker": "SPEAKER_02",
        "text": "Hej.",
    }
    assert result.to_metadata()["segments_omitted_reason"] is None


async def test_segments_are_all_or_nothing_across_files(spool_contract) -> None:
    transcriber = _transcriber(
        TranscribedAudio(
            FILE_TEXT, 10.0, diarization="external", transcript_segments=FILE_SEGMENTS
        ),
        TranscribedAudio(FILE_TEXT, 10.0, diarization="external"),
    )

    result = await _run(spool_contract, [_file("a.mp3"), _file("b.mp3")], transcriber)

    assert result.segments is None
    assert result.to_metadata()["segments"] is None


async def test_oversized_segments_are_omitted_with_a_reason(
    spool_contract,
    monkeypatch,
) -> None:
    monkeypatch.setattr(transcription, "MAX_SEGMENTS_BYTES", 10)
    transcriber = _transcriber(
        TranscribedAudio(
            FILE_TEXT, 10.0, diarization="external", transcript_segments=FILE_SEGMENTS
        ),
    )

    result = await _run(spool_contract, [_file("a.mp3")], transcriber)

    assert result.segments is None
    assert result.to_metadata()["segments_omitted_reason"] == "too_large"


FILE_WORDS = (
    TranscriptWord("Hej.", 0.1, 0.42, probability=0.95),
    TranscriptWord("Hallå.", 5.2, 5.8, probability=0.0),
)
TIMED_SEGMENTS = (
    TranscriptSegment("Hej.", 0.0, 4.0, speaker="SPEAKER_00", words=FILE_WORDS[:1]),
    TranscriptSegment("Hallå.", 5.0, 9.5, speaker="SPEAKER_01", words=FILE_WORDS[1:]),
)


async def test_words_are_keyed_to_the_stored_segment_index_across_files(
    spool_contract,
) -> None:
    transcriber = _transcriber(
        TranscribedAudio(
            FILE_TEXT, 10.0, diarization="external", transcript_segments=TIMED_SEGMENTS
        ),
        TranscribedAudio(
            FILE_TEXT,
            10.0,
            diarization="external",
            transcript_segments=(
                TranscriptSegment("Hej.", 0.0, 4.0, speaker="SPEAKER_00"),
                TIMED_SEGMENTS[1],
            ),
        ),
    )

    result = await _run(spool_contract, [_file("a.mp3"), _file("b.mp3")], transcriber)

    # The second file's first segment has no words, so index 2 is skipped and
    # index 3 (its second segment) keeps its per-file timestamps.
    assert result.words == [
        {
            "segment_index": 0,
            "words": [{"word": "Hej.", "start": 0.1, "end": 0.42, "probability": 0.95}],
        },
        {
            "segment_index": 1,
            "words": [{"word": "Hallå.", "start": 5.2, "end": 5.8, "probability": 0.0}],
        },
        {
            "segment_index": 3,
            "words": [{"word": "Hallå.", "start": 5.2, "end": 5.8, "probability": 0.0}],
        },
    ]
    assert result.words_omitted_reason is None
    assert "words" not in result.to_metadata()
    assert result.to_metadata()["words_omitted_reason"] is None


async def test_words_are_dropped_with_the_segments_they_anchor_to(
    spool_contract,
    monkeypatch,
) -> None:
    monkeypatch.setattr(transcription, "MAX_SEGMENTS_BYTES", 10)
    transcriber = _transcriber(
        TranscribedAudio(
            FILE_TEXT, 10.0, diarization="external", transcript_segments=TIMED_SEGMENTS
        ),
    )

    result = await _run(spool_contract, [_file("a.mp3")], transcriber)

    assert result.segments is None
    assert result.words is None
    assert result.to_metadata()["words_omitted_reason"] == "segments_unavailable"


async def test_oversized_words_are_omitted_but_segments_kept(
    spool_contract, monkeypatch
) -> None:
    monkeypatch.setattr(transcription, "MAX_WORDS_BYTES", 10)
    transcriber = _transcriber(
        TranscribedAudio(
            FILE_TEXT, 10.0, diarization="external", transcript_segments=TIMED_SEGMENTS
        ),
    )

    result = await _run(spool_contract, [_file("a.mp3")], transcriber)

    assert result.segments is not None
    assert result.words is None
    assert result.to_metadata()["words_omitted_reason"] == "too_large"


# Pinned upstream contract: eneo-ai/vemsa@97096dcacb919ed8f8258552f807b39d5bdc4ddb

SHARED_CASES = json.loads(
    (Path(__file__).parents[3] / "fixtures/speaker_review.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", SHARED_CASES, ids=lambda case: case["name"])
async def test_shared_vemsa_case_adapter_checkpoint_correction_render(
    spool_contract, case
):
    wire = case["result"]
    source = TranscribedAudio(
        wire["text"],
        wire["duration_seconds"],
        diarization="external",
        transcript_segments=_parse_result_segments(wire["segments"]),
        speaker_review=wire["speaker_review"],
    )
    result = await _run(spool_contract, [_file("a.mp3")], _transcriber(source))
    assert result.text == wire["text"]
    segments = result.segments
    assert segments
    assert [s.get("speaker_attribution") for s in segments] == [
        s["speaker_attribution"] for s in wire["segments"]
    ]
    assert [s["start"] for s in segments] == [s["start"] for s in wire["segments"]]
    assert [s["text"] for s in segments] == [s["text"] for s in wire["segments"]]
    for index, segment in enumerate(segments):
        for decision in ("confirmed", "unresolved"):
            speaker = (
                segment["speaker"] or "SPEAKER_00" if decision == "confirmed" else None
            )
            edit = TranscriptSpeakerEdit(
                index, None, None, None, segment["speaker"], speaker, decision
            )
            public = TranscriptSpeakerEditPublic.model_validate(edit.as_json())
            restored = TranscriptSpeakerEdit(**public.model_dump())
            validate_speaker_edits(segments, [restored])
            rendered = apply_to_rendered_transcript(
                result.text, segments, [], [restored]
            )
            assert rendered is not None
            assert segment["text"] in rendered
            assert ("[Talare går inte att avgöra]" in rendered) == (
                decision == "unresolved"
            )


async def test_two_files_namespace_overlap_ids_and_keep_unknown_speakers_in_inventory(
    spool_contract,
):
    wire = next(case["result"] for case in SHARED_CASES if case["name"] == "overlap")
    source = TranscribedAudio(
        wire["text"],
        3,
        diarization="external",
        transcript_segments=_parse_result_segments(wire["segments"]),
        speaker_review=wire["speaker_review"],
    )
    files = [_file("a.mp3"), _file("b.mp3")]
    result = await _run(spool_contract, files, _transcriber(source, source))
    assert result.segments[1]["overlap_ids"] == [f"{files[0].id}:overlap_0000"]
    assert result.segments[4]["overlap_ids"] == [f"{files[1].id}:overlap_0000"]
    assert (
        result.speaker_review["files"][1]["overlaps"][0]["id"]
        == result.segments[4]["overlap_ids"][0]
    )
    assert [s["speaker"] for s in result.segments] == ["SPEAKER_00"] * 3 + [
        "SPEAKER_01"
    ] * 3
    assert [entry["segment_index"] for entry in result.words] == list(range(6))
    assert all("ses" not in entry["samples"] for entry in result.speakers)


async def test_review_size_fallback_retains_uncertainty(spool_contract, monkeypatch):
    wire = next(case["result"] for case in SHARED_CASES if case["name"] == "overlap")
    source = TranscribedAudio(
        wire["text"],
        3,
        diarization="external",
        transcript_segments=_parse_result_segments(wire["segments"]),
        speaker_review=wire["speaker_review"],
    )
    monkeypatch.setattr(transcription, "MAX_SEGMENTS_BYTES", 1)
    result = await _run(spool_contract, [_file("a.mp3")], _transcriber(source))
    assert result.segments is None
    assert result.words is None
    assert result.segments_omitted_reason == "too_large"
    assert "[Överlappande tal – osäker talare]: ses" in result.text
    assert "SPEAKER_00: ses" not in result.text


async def test_final_segment_order_remaps_words_and_keeps_overlap_precision(
    spool_contract,
):
    source = TranscribedAudio(
        "unused",
        4,
        diarization="external",
        transcript_segments=(
            TranscriptSegment(
                "Sist",
                2.1234567,
                3,
                speaker="SPEAKER_01",
                words=(TranscriptWord("Sist", 2.1234567, 3),),
            ),
            TranscriptSegment(
                "Först",
                0.1234567,
                1,
                speaker="SPEAKER_00",
                speaker_attribution="provisional",
                overlap_ids=("overlap_0000",),
                words=(TranscriptWord("Först", 0.1234567, 1),),
            ),
        ),
        speaker_review={
            "version": 1,
            "overlap_detection": "available",
            "overlaps": [
                {
                    "id": "overlap_0000",
                    "start": 0.1234567,
                    "end": 0.1234568,
                    "detected_speaker_count": 2,
                }
            ],
        },
    )
    result = await _run(spool_contract, [_file("a.mp3")], _transcriber(source))
    assert result.segments[0]["text"] == "Först"
    assert result.words[0]["segment_index"] == 0
    assert result.words[0]["words"][0]["start"] == 0.1234567
    assert result.speaker_review["files"][0]["overlaps"][0]["end"] == 0.1234568


async def test_empty_first_file_preserves_review_file_identity(spool_contract):
    wire = next(case["result"] for case in SHARED_CASES if case["name"] == "overlap")
    source = TranscribedAudio(
        wire["text"],
        3,
        diarization="external",
        transcript_segments=_parse_result_segments(wire["segments"]),
        speaker_review=wire["speaker_review"],
    )
    result = await _run(
        spool_contract,
        [_file("empty.mp3"), _file("speech.mp3")],
        _transcriber(TranscribedAudio("", 0, diarization="external"), source),
    )
    assert result.text.startswith("## Del 2\n")
    assert all(segment["file_index"] == 1 for segment in result.segments)
