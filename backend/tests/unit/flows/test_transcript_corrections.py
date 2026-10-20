"""Corrections anchor to the stored segments and apply on read."""

import pytest

from eneo.flows.transcript_corrections import (
    TranscriptCorrectionInvalidOccurrenceError,
    TranscriptCorrectionOccurrence,
    TranscriptSpeakerEdit,
    TranscriptSpeakerEditInvalidError,
    apply_corrections_and_speaker_edits,
    normalize_speaker_names,
    render_corrected_transcript,
    segments_content_hash,
    validate_correction_partitions,
    validate_occurrences,
    validate_speaker_edits,
)


def _segments():
    return [
        {
            "file_index": 0,
            "start": 0.0,
            "end": 5.0,
            "speaker": "SPEAKER_00",
            "text": "sugary tea",
        },
        {
            "file_index": 0,
            "start": 5.0,
            "end": 9.0,
            "speaker": "SPEAKER_01",
            "text": "yes please",
        },
    ]


def _occurrence(**extra):
    base = dict(
        segment_index=0, char_start=0, char_end=6, original="sugary", corrected="sugar"
    )
    return TranscriptCorrectionOccurrence(**{**base, **extra})


def test_hash_is_stable_and_changes_with_the_text():
    assert len(segments_content_hash(_segments())) == 64
    assert segments_content_hash(_segments()) == segments_content_hash(_segments())
    changed = _segments()
    changed[0]["text"] = "sugar tea"
    assert segments_content_hash(changed) != segments_content_hash(_segments())


def test_occurrences_must_anchor_exactly():
    validate_occurrences(_segments(), [_occurrence()])
    for bad, reason in (
        (_occurrence(segment_index=5), "segment_index_out_of_range"),
        (_occurrence(char_end=99), "char_range_invalid"),
        (_occurrence(original="sugar"), "original_mismatch"),
    ):
        with pytest.raises(TranscriptCorrectionInvalidOccurrenceError) as exc:
            validate_occurrences(_segments(), [bad])
        assert exc.value.reason == reason
    with pytest.raises(TranscriptCorrectionInvalidOccurrenceError) as exc:
        validate_occurrences(
            _segments(),
            [_occurrence(), _occurrence(char_start=3, char_end=10, original="ary tea")],
        )
    assert exc.value.reason == "overlapping_ranges"


def test_speaker_edits_anchor_to_the_stored_label():
    whole = TranscriptSpeakerEdit(1, None, None, None, "SPEAKER_01", "SPEAKER_00")
    validate_speaker_edits(_segments(), [whole])
    wrong = TranscriptSpeakerEdit(1, None, None, None, "SPEAKER_00", "SPEAKER_02")
    with pytest.raises(TranscriptSpeakerEditInvalidError) as exc:
        validate_speaker_edits(_segments(), [wrong])
    assert exc.value.reason == "original_speaker_mismatch"
    unresolved_with_name = TranscriptSpeakerEdit(
        1, None, None, None, "SPEAKER_01", "SPEAKER_00", decision="unresolved"
    )
    with pytest.raises(TranscriptSpeakerEditInvalidError) as exc:
        validate_speaker_edits(_segments(), [unresolved_with_name])
    assert exc.value.reason == "invalid_decision"
    span = TranscriptSpeakerEdit(1, 4, 10, "please", "SPEAKER_01", "SPEAKER_00")
    with pytest.raises(TranscriptSpeakerEditInvalidError) as exc:
        validate_speaker_edits(_segments(), [whole, span])
    assert exc.value.reason == "whole_segment_conflicts_with_span"


def test_a_correction_cannot_cross_a_speaker_boundary():
    span = TranscriptSpeakerEdit(0, 7, 10, "tea", "SPEAKER_00", "SPEAKER_01")
    crossing = _occurrence(char_start=4, char_end=9, original="ry te", corrected="x")
    with pytest.raises(TranscriptCorrectionInvalidOccurrenceError) as exc:
        validate_correction_partitions([crossing], [span])
    assert exc.value.reason == "crosses_speaker_boundary"


def test_names_are_trimmed_and_limited_to_known_labels():
    names = normalize_speaker_names(
        {"SPEAKER_00": " Anna ", "SPEAKER_01": ""},
        segments=_segments(),
        speaker_edits=[],
    )
    assert names == {"SPEAKER_00": "Anna", "SPEAKER_01": None}
    with pytest.raises(TranscriptSpeakerEditInvalidError) as exc:
        normalize_speaker_names(
            {"SPEAKER_07": "x"}, segments=_segments(), speaker_edits=[]
        )
    assert exc.value.reason == "unknown_speaker_label"


def test_apply_replaces_text_and_speakers_and_skips_stale_anchors():
    stale = _occurrence(
        segment_index=1, char_start=0, char_end=3, original="nej", corrected="ja"
    )
    span = TranscriptSpeakerEdit(1, 4, 10, "please", "SPEAKER_01", "SPEAKER_00")
    corrected, skipped_occurrences, skipped_edits = apply_corrections_and_speaker_edits(
        _segments(), [_occurrence(), stale], [span]
    )
    assert corrected[0]["text"] == "sugar tea"
    assert skipped_occurrences == [stale]
    assert skipped_edits == []
    assert corrected[1]["speaker_runs"] == [
        {"char_start": 0, "char_end": 4, "speaker": "SPEAKER_01", "decision": None},
        {
            "char_start": 4,
            "char_end": 10,
            "speaker": "SPEAKER_00",
            "decision": "confirmed",
        },
    ]
    # The stored segments are untouched.
    assert _segments()[0]["text"] == "sugary tea"


def test_rendered_transcript_applies_everything_and_names_speakers():
    span = TranscriptSpeakerEdit(1, 4, 10, "please", "SPEAKER_01", "SPEAKER_00")
    text = render_corrected_transcript(
        _segments(), [_occurrence()], [span], {"SPEAKER_00": "Anna"}
    )
    assert text.split("\n") == [
        "[00:00:00 - 00:00:05] Anna: sugar tea",
        "[00:00:05 - 00:00:09] SPEAKER_01: yes",
        "[00:00:05 - 00:00:09] Anna: please",
    ]
