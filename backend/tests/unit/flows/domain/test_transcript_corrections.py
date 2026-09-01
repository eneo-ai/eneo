from __future__ import annotations

import pytest

from eneo.flows.domain.transcript_corrections import (
    MAX_CORRECTION_OCCURRENCES,
    TranscriptCorrectionInvalidOccurrenceError,
    TranscriptCorrectionOccurrence,
    apply_corrections,
    segments_content_hash,
    sort_occurrences,
    validate_occurrences,
)


def _segment(text: str, *, speaker: str | None = "SPEAKER_00") -> dict:
    return {
        "file_index": 1,
        "start": 0.0,
        "end": 4.0,
        "speaker": speaker,
        "text": text,
    }


def _occurrence(
    *,
    segment_index: int = 0,
    char_start: int,
    char_end: int,
    original: str,
    corrected: str,
) -> TranscriptCorrectionOccurrence:
    return TranscriptCorrectionOccurrence(
        segment_index=segment_index,
        char_start=char_start,
        char_end=char_end,
        original=original,
        corrected=corrected,
    )


class TestSegmentsContentHash:
    def test_hash_ignores_key_order_but_not_values(self) -> None:
        segments = [{"text": "Hej", "start": 0.0, "end": 1.0}]
        reordered = [{"end": 1.0, "start": 0.0, "text": "Hej"}]
        changed = [{"text": "Hej!", "start": 0.0, "end": 1.0}]

        assert segments_content_hash(segments) == segments_content_hash(reordered)
        assert segments_content_hash(segments) != segments_content_hash(changed)

    def test_hash_is_stable_for_non_ascii_text(self) -> None:
        segments = [_segment("Çagri höll i mötet.")]

        assert segments_content_hash(segments) == segments_content_hash(
            [dict(segments[0])]
        )


class TestValidateOccurrences:
    def test_accepts_matching_occurrences(self) -> None:
        segments = [_segment("Vi frågade sugary om planen.")]
        occurrence = _occurrence(
            char_start=11, char_end=17, original="sugary", corrected="Çagri"
        )

        validate_occurrences(segments, [occurrence])

    def test_rejects_segment_index_out_of_range(self) -> None:
        segments = [_segment("Hej.")]
        occurrence = _occurrence(
            segment_index=1, char_start=0, char_end=3, original="Hej", corrected="Nej"
        )

        with pytest.raises(TranscriptCorrectionInvalidOccurrenceError) as excinfo:
            validate_occurrences(segments, [occurrence])
        assert excinfo.value.reason == "segment_index_out_of_range"

    def test_rejects_char_range_past_text_end(self) -> None:
        segments = [_segment("Hej.")]
        occurrence = _occurrence(
            char_start=2, char_end=10, original="j.", corrected="x"
        )

        with pytest.raises(TranscriptCorrectionInvalidOccurrenceError) as excinfo:
            validate_occurrences(segments, [occurrence])
        assert excinfo.value.reason == "char_range_invalid"

    def test_rejects_original_mismatch(self) -> None:
        segments = [_segment("Vi frågade sugary om planen.")]
        occurrence = _occurrence(
            char_start=11, char_end=17, original="sockry", corrected="Çagri"
        )

        with pytest.raises(TranscriptCorrectionInvalidOccurrenceError) as excinfo:
            validate_occurrences(segments, [occurrence])
        assert excinfo.value.reason == "original_mismatch"

    def test_rejects_overlapping_ranges_within_a_segment(self) -> None:
        segments = [_segment("abcdef")]
        occurrences = [
            _occurrence(char_start=0, char_end=3, original="abc", corrected="x"),
            _occurrence(char_start=2, char_end=5, original="cde", corrected="y"),
        ]

        with pytest.raises(TranscriptCorrectionInvalidOccurrenceError) as excinfo:
            validate_occurrences(segments, occurrences)
        assert excinfo.value.reason == "overlapping_ranges"

    def test_adjacent_ranges_do_not_overlap(self) -> None:
        segments = [_segment("abcdef")]
        occurrences = [
            _occurrence(char_start=0, char_end=3, original="abc", corrected="x"),
            _occurrence(char_start=3, char_end=6, original="def", corrected="y"),
        ]

        validate_occurrences(segments, occurrences)

    def test_rejects_oversized_occurrence_lists(self) -> None:
        segments = [_segment("a" * 3)]
        occurrence = _occurrence(char_start=0, char_end=1, original="a", corrected="b")

        with pytest.raises(TranscriptCorrectionInvalidOccurrenceError) as excinfo:
            validate_occurrences(
                segments, [occurrence] * (MAX_CORRECTION_OCCURRENCES + 1)
            )
        assert excinfo.value.reason == "too_many_occurrences"

    def test_offsets_are_character_based_for_non_ascii_text(self) -> None:
        segments = [_segment("Çagri sa hej.")]
        occurrence = _occurrence(
            char_start=0, char_end=5, original="Çagri", corrected="Cagri"
        )

        validate_occurrences(segments, [occurrence])


class TestApplyCorrections:
    def test_applies_multiple_occurrences_right_to_left_within_a_line(self) -> None:
        segments = [_segment("sugary pratade med sugary igår.")]
        occurrences = [
            _occurrence(char_start=0, char_end=6, original="sugary", corrected="Çagri"),
            _occurrence(
                char_start=19, char_end=25, original="sugary", corrected="Çagri"
            ),
        ]

        corrected, skipped = apply_corrections(segments, occurrences)

        assert corrected[0]["text"] == "Çagri pratade med Çagri igår."
        assert skipped == []

    def test_replacement_length_change_does_not_shift_earlier_offsets(self) -> None:
        segments = [_segment("aa bb cc")]
        occurrences = [
            _occurrence(char_start=0, char_end=2, original="aa", corrected="lång text"),
            _occurrence(char_start=6, char_end=8, original="cc", corrected="x"),
        ]

        corrected, skipped = apply_corrections(segments, occurrences)

        assert corrected[0]["text"] == "lång text bb x"
        assert skipped == []

    def test_empty_corrected_deletes_the_span(self) -> None:
        segments = [_segment("Hej alltså världen.")]
        occurrences = [
            _occurrence(char_start=3, char_end=10, original=" alltså", corrected="")
        ]

        corrected, skipped = apply_corrections(segments, occurrences)

        assert corrected[0]["text"] == "Hej världen."
        assert skipped == []

    def test_skips_mismatched_and_out_of_range_occurrences(self) -> None:
        segments = [_segment("Hej världen.")]
        mismatched = _occurrence(
            char_start=0, char_end=3, original="Nej", corrected="Tja"
        )
        out_of_range = _occurrence(
            segment_index=5, char_start=0, char_end=3, original="Hej", corrected="Tja"
        )

        corrected, skipped = apply_corrections(segments, [mismatched, out_of_range])

        assert corrected[0]["text"] == "Hej världen."
        assert set(skipped) == {mismatched, out_of_range}

    def test_does_not_mutate_the_input_segments(self) -> None:
        segments = [_segment("Hej världen.")]
        occurrences = [
            _occurrence(char_start=0, char_end=3, original="Hej", corrected="Tja")
        ]

        corrected, _ = apply_corrections(segments, occurrences)

        assert segments[0]["text"] == "Hej världen."
        assert corrected[0]["text"] == "Tja världen."
        assert corrected[0]["speaker"] == segments[0]["speaker"]

    def test_corrections_only_touch_the_text_field(self) -> None:
        segments = [_segment("Hej.", speaker="SPEAKER_03")]
        occurrences = [
            _occurrence(char_start=0, char_end=3, original="Hej", corrected="Nej")
        ]

        corrected, _ = apply_corrections(segments, occurrences)

        assert corrected[0]["speaker"] == "SPEAKER_03"
        assert corrected[0]["start"] == segments[0]["start"]
        assert corrected[0]["end"] == segments[0]["end"]


class TestSortOccurrences:
    def test_sorts_by_segment_then_char_start(self) -> None:
        second_line = _occurrence(
            segment_index=1, char_start=0, char_end=1, original="a", corrected="b"
        )
        first_line_late = _occurrence(
            segment_index=0, char_start=9, char_end=10, original="c", corrected="d"
        )
        first_line_early = _occurrence(
            segment_index=0, char_start=2, char_end=3, original="e", corrected="f"
        )

        ordered = sort_occurrences([second_line, first_line_late, first_line_early])

        assert ordered == [first_line_early, first_line_late, second_line]
