"""Word timings go out exactly as the per-word presenter built them, from one
nested validation."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest

from eneo.flows.api.flow_models import (
    FlowTranscriptWordsPublic,
    TranscriptSegmentWordsPublic,
    TranscriptWordPublic,
)
from eneo.flows.api.flow_run_transcript_words_router import _present_transcript_words
from eneo.flows.application.flow_transcript_words_service import (
    FlowTranscriptWordsView,
)
from eneo.flows.domain.transcript_words import FlowStepTranscriptWords

RUN_ID = UUID("00000000-0000-0000-0000-000000000301")
STEP_ID = UUID("00000000-0000-0000-0000-000000000101")
STORED_AT = datetime(2026, 3, 17, 10, 12, tzinfo=timezone.utc)


def _view(words_json: list[dict[str, Any]], *, stale: bool = False):
    return FlowTranscriptWordsView(
        words=FlowStepTranscriptWords(
            id=UUID("00000000-0000-0000-0000-000000000901"),
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            flow_id=UUID("00000000-0000-0000-0000-000000000201"),
            flow_run_id=RUN_ID,
            step_id=STEP_ID,
            segments_hash="a" * 64,
            alignment="forced",
            words_json=words_json,
            created_at=STORED_AT,
            updated_at=STORED_AT,
        ),
        stale=stale,
    )


def _per_word_presenter(view: FlowTranscriptWordsView) -> FlowTranscriptWordsPublic:
    """The presenter as it was before one nested validation replaced it."""
    return FlowTranscriptWordsPublic(
        flow_run_id=view.words.flow_run_id,
        step_id=view.words.step_id,
        segments_hash=view.words.segments_hash,
        alignment=view.words.alignment,
        stale=view.stale,
        segments=[
            TranscriptSegmentWordsPublic(
                segment_index=int(entry["segment_index"]),
                speaker_attribution=entry.get("speaker_attribution"),
                overlap_ids=entry.get("overlap_ids", []),
                words=[
                    TranscriptWordPublic.model_validate(word)
                    for word in entry.get("words", [])
                ],
            )
            for entry in view.words.words_json
        ],
        created_at=view.words.created_at,
        updated_at=view.words.updated_at,
    )


STORED: list[dict[str, Any]] = [
    {
        "segment_index": 0,
        "words": [
            {"word": "Vi", "start": 0.1, "end": 0.3, "probability": 0.98},
            {"word": "frågade", "start": 0.35, "end": 0.9},
        ],
    },
    {
        "segment_index": 1,
        "speaker_attribution": "provisional",
        "overlap_ids": ["file-1:overlap_0000"],
        "words": [
            {"word": "Ja", "start": 1.0, "end": 1.2, "probability": None, "x": 1}
        ],
    },
    {"segment_index": 2.0, "words": []},
    {"segment_index": 3.7},
    {
        "segment_index": "4",
        "future_key": {"dropped": True},
        "words": [{"word": "0,0", "start": 4, "end": 5, "probability": 0.0}],
    },
]

GOLDEN: dict[str, Any] = {
    "flow_run_id": str(RUN_ID),
    "step_id": str(STEP_ID),
    "segments_hash": "a" * 64,
    "alignment": "forced",
    "stale": True,
    "segments": [
        {
            "speaker_attribution": None,
            "overlap_ids": [],
            "segment_index": 0,
            "words": [
                {"word": "Vi", "start": 0.1, "end": 0.3, "probability": 0.98},
                {"word": "frågade", "start": 0.35, "end": 0.9, "probability": None},
            ],
        },
        {
            "speaker_attribution": "provisional",
            "overlap_ids": ["file-1:overlap_0000"],
            "segment_index": 1,
            "words": [{"word": "Ja", "start": 1.0, "end": 1.2, "probability": None}],
        },
        {
            "speaker_attribution": None,
            "overlap_ids": [],
            "segment_index": 2,
            "words": [],
        },
        {
            "speaker_attribution": None,
            "overlap_ids": [],
            "segment_index": 3,
            "words": [],
        },
        {
            "speaker_attribution": None,
            "overlap_ids": [],
            "segment_index": 4,
            "words": [{"word": "0,0", "start": 4.0, "end": 5.0, "probability": 0.0}],
        },
    ],
    "created_at": "2026-03-17T10:12:00Z",
    "updated_at": "2026-03-17T10:12:00Z",
}


def test_words_match_the_golden_response() -> None:
    view = _view(STORED, stale=True)

    assert _present_transcript_words(view).model_dump(mode="json") == GOLDEN
    assert _per_word_presenter(view).model_dump(mode="json") == GOLDEN


def test_words_match_the_per_word_presenter_on_a_long_recording() -> None:
    rng = random.Random(7)
    stored: list[dict[str, Any]] = []
    for index in range(3_000):
        entry: dict[str, Any] = {
            "segment_index": rng.choice([index, float(index), index + 0.5, str(index)])
        }
        if rng.random() < 0.9:
            entry["words"] = [
                {
                    "word": rng.choice(["hej", "och", "Sundsvall,", "kommun."]),
                    "start": index + offset / 10,
                    "end": index + offset / 10 + 0.05,
                    **(
                        {"probability": rng.choice([None, 0.0, rng.random()])}
                        if rng.random() < 0.8
                        else {}
                    ),
                }
                for offset in range(rng.randint(0, 6))
            ]
        if rng.random() < 0.2:
            entry["speaker_attribution"] = "provisional"
        if rng.random() < 0.2:
            entry["overlap_ids"] = [f"file-0:overlap_{index:04d}"]
        stored.append(entry)
    view = _view(stored)

    expected = _per_word_presenter(view)
    actual = _present_transcript_words(view)

    assert actual.model_dump(mode="json") == expected.model_dump(mode="json")
    assert actual.model_dump(mode="json", exclude_unset=True) == expected.model_dump(
        mode="json", exclude_unset=True
    )


def test_words_are_validated_in_one_pass_not_one_call_per_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def per_word_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("one model_validate call per word")

    monkeypatch.setattr(TranscriptWordPublic, "model_validate", per_word_call)

    assert (
        _present_transcript_words(_view(STORED, stale=True)).model_dump(mode="json")
        == GOLDEN
    )


def test_unusable_stored_entries_are_still_refused() -> None:
    with pytest.raises(ValueError):
        _present_transcript_words(_view([{"segment_index": "first", "words": []}]))
    with pytest.raises(ValueError):
        _present_transcript_words(_view([{"segment_index": -1, "words": []}]))
    with pytest.raises(KeyError):
        _present_transcript_words(_view([{"words": []}]))
