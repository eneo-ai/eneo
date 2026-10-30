"""Transcript source lines are typed without changing the keys they are
stored with."""

from __future__ import annotations

from eneo.flows.api.flow_transcript_source_router import (
    TranscriptSourceSegmentPublic,
)


def _wire(stored: dict[str, object]) -> dict[str, object]:
    return TranscriptSourceSegmentPublic.model_validate(stored).model_dump(
        mode="json", exclude_unset=True
    )


def test_a_plain_line_gains_no_keys():
    stored: dict[str, object] = {
        "segment_index": 3,
        "file_index": 0,
        "start": 1.5,
        "end": 2.25,
        "speaker": None,
        "text": "Hej.",
    }

    assert _wire(stored) == stored


def test_a_marked_line_keeps_its_marks_and_unknown_keys():
    stored: dict[str, object] = {
        "segment_index": 0,
        "file_index": 1,
        "start": 0.0,
        "end": 1.0,
        "speaker": "SPEAKER_01",
        "text": "Ja.",
        "speaker_attribution": None,
        "overlap_ids": ["file-1:overlap_0000"],
        "future_key": {"kept": True},
    }

    assert _wire(stored) == stored
