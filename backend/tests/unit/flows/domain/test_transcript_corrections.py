from __future__ import annotations

import pytest

from eneo.flows.domain.transcript_corrections import (
    MAX_CORRECTION_OCCURRENCES,
    MAX_SPEAKER_EDITS,
    TranscriptCorrectionInvalidOccurrenceError,
    TranscriptCorrectionOccurrence,
    TranscriptSpeakerEdit,
    TranscriptSpeakerEditInvalidError,
    apply_corrections,
    apply_corrections_and_speaker_edits,
    apply_to_rendered_transcript,
    segments_content_hash,
    sort_occurrences,
    sort_speaker_edits,
    validate_occurrences,
    validate_speaker_edits,
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


def _speaker_edit(
    *,
    segment_index: int = 0,
    char_start: int | None = None,
    char_end: int | None = None,
    original: str | None = None,
    original_speaker: str = "SPEAKER_00",
    speaker: str = "SPEAKER_01",
) -> TranscriptSpeakerEdit:
    return TranscriptSpeakerEdit(
        segment_index=segment_index,
        char_start=char_start,
        char_end=char_end,
        original=original,
        original_speaker=original_speaker,
        speaker=speaker,
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


class TestValidateSpeakerEdits:
    def test_accepts_whole_segment_and_span_edits(self) -> None:
        segments = [
            _segment("Vi frågade sugary om planen."),
            _segment("sugary svarade direkt.", speaker="SPEAKER_01"),
        ]
        edits = [
            _speaker_edit(),
            _speaker_edit(
                segment_index=1,
                char_start=0,
                char_end=6,
                original="sugary",
                original_speaker="SPEAKER_01",
                speaker="SPEAKER_02",
            ),
        ]

        validate_speaker_edits(segments, edits)

    def test_rejects_segment_index_out_of_range(self) -> None:
        with pytest.raises(TranscriptSpeakerEditInvalidError) as excinfo:
            validate_speaker_edits([_segment("Hej.")], [_speaker_edit(segment_index=1)])
        assert excinfo.value.reason == "segment_index_out_of_range"

    def test_rejects_original_speaker_mismatch(self) -> None:
        with pytest.raises(TranscriptSpeakerEditInvalidError) as excinfo:
            validate_speaker_edits(
                [_segment("Hej.")],
                [_speaker_edit(original_speaker="SPEAKER_01", speaker="SPEAKER_02")],
            )
        assert excinfo.value.reason == "original_speaker_mismatch"

    def test_rejects_segment_without_speaker(self) -> None:
        with pytest.raises(TranscriptSpeakerEditInvalidError) as excinfo:
            validate_speaker_edits([_segment("Hej.", speaker=None)], [_speaker_edit()])
        assert excinfo.value.reason == "segment_has_no_speaker"

    def test_rejects_noop_edit(self) -> None:
        with pytest.raises(TranscriptSpeakerEditInvalidError) as excinfo:
            validate_speaker_edits(
                [_segment("Hej.")], [_speaker_edit(speaker="SPEAKER_00")]
            )
        assert excinfo.value.reason == "speaker_unchanged"

    def test_rejects_span_text_mismatch(self) -> None:
        with pytest.raises(TranscriptSpeakerEditInvalidError) as excinfo:
            validate_speaker_edits(
                [_segment("Hej världen.")],
                [_speaker_edit(char_start=0, char_end=3, original="Nej")],
            )
        assert excinfo.value.reason == "original_mismatch"

    def test_rejects_span_past_text_end(self) -> None:
        with pytest.raises(TranscriptSpeakerEditInvalidError) as excinfo:
            validate_speaker_edits(
                [_segment("Hej.")],
                [_speaker_edit(char_start=2, char_end=10, original="j.")],
            )
        assert excinfo.value.reason == "char_range_invalid"

    def test_rejects_partially_null_span(self) -> None:
        with pytest.raises(TranscriptSpeakerEditInvalidError) as excinfo:
            validate_speaker_edits(
                [_segment("Hej.")], [_speaker_edit(char_start=0, char_end=3)]
            )
        assert excinfo.value.reason == "char_range_invalid"

    def test_rejects_overlapping_spans(self) -> None:
        segments = [_segment("abcdef")]
        edits = [
            _speaker_edit(char_start=0, char_end=3, original="abc"),
            _speaker_edit(
                char_start=2, char_end=5, original="cde", speaker="SPEAKER_02"
            ),
        ]

        with pytest.raises(TranscriptSpeakerEditInvalidError) as excinfo:
            validate_speaker_edits(segments, edits)
        assert excinfo.value.reason == "overlapping_speaker_spans"

    def test_adjacent_spans_do_not_overlap(self) -> None:
        segments = [_segment("abcdef")]
        edits = [
            _speaker_edit(char_start=0, char_end=3, original="abc"),
            _speaker_edit(
                char_start=3, char_end=6, original="def", speaker="SPEAKER_02"
            ),
        ]

        validate_speaker_edits(segments, edits)

    def test_rejects_whole_segment_combined_with_span(self) -> None:
        segments = [_segment("abcdef")]
        edits = [
            _speaker_edit(),
            _speaker_edit(
                char_start=0, char_end=3, original="abc", speaker="SPEAKER_02"
            ),
        ]

        with pytest.raises(TranscriptSpeakerEditInvalidError) as excinfo:
            validate_speaker_edits(segments, edits)
        assert excinfo.value.reason == "whole_segment_conflicts_with_span"

    def test_allows_labels_not_present_in_the_transcript(self) -> None:
        validate_speaker_edits(
            [_segment("Hej.")], [_speaker_edit(speaker="SPEAKER_07")]
        )

    def test_rejects_oversized_edit_lists(self) -> None:
        edits = [_speaker_edit()] * (MAX_SPEAKER_EDITS + 1)

        with pytest.raises(TranscriptSpeakerEditInvalidError) as excinfo:
            validate_speaker_edits([_segment("Hej.")], edits)
        assert excinfo.value.reason == "too_many_speaker_edits"


class TestApplySpeakerEdits:
    def test_whole_segment_edit_replaces_speaker_and_keeps_text(self) -> None:
        segments = [_segment("Hej världen.")]

        corrected, skipped_occurrences, skipped_edits = (
            apply_corrections_and_speaker_edits(segments, [], [_speaker_edit()])
        )

        assert corrected[0]["speaker"] == "SPEAKER_01"
        assert corrected[0]["text"] == "Hej världen."
        assert "speaker_runs" not in corrected[0]
        assert skipped_occurrences == []
        assert skipped_edits == []

    def test_span_edit_produces_runs_in_corrected_space(self) -> None:
        segments = [_segment("Vi frågade sugary om planen.")]
        occurrences = [
            _occurrence(
                char_start=11, char_end=17, original="sugary", corrected="Çagri"
            )
        ]
        edits = [_speaker_edit(char_start=18, char_end=28, original="om planen.")]

        corrected, _, skipped_edits = apply_corrections_and_speaker_edits(
            segments, occurrences, edits
        )

        assert corrected[0]["text"] == "Vi frågade Çagri om planen."
        assert corrected[0]["speaker"] == "SPEAKER_00"
        assert corrected[0]["speaker_runs"] == [
            {"char_start": 0, "char_end": 17, "speaker": "SPEAKER_00"},
            {"char_start": 17, "char_end": 27, "speaker": "SPEAKER_01"},
        ]
        assert skipped_edits == []

    def test_span_boundary_inside_replacement_clamps(self) -> None:
        segments = [_segment("Vi frågade sugary om planen.")]
        occurrences = [
            _occurrence(char_start=11, char_end=17, original="sugary", corrected="X")
        ]
        edits = [_speaker_edit(char_start=14, char_end=28, original="ary om planen.")]

        corrected, _, _ = apply_corrections_and_speaker_edits(
            segments, occurrences, edits
        )

        assert corrected[0]["text"] == "Vi frågade X om planen."
        assert corrected[0]["speaker_runs"] == [
            {"char_start": 0, "char_end": 12, "speaker": "SPEAKER_00"},
            {"char_start": 12, "char_end": 23, "speaker": "SPEAKER_01"},
        ]

    def test_full_coverage_spans_collapse_to_speaker_replacement(self) -> None:
        segments = [_segment("Hej världen.")]
        edits = [_speaker_edit(char_start=0, char_end=12, original="Hej världen.")]

        corrected, _, _ = apply_corrections_and_speaker_edits(segments, [], edits)

        assert corrected[0]["speaker"] == "SPEAKER_01"
        assert "speaker_runs" not in corrected[0]

    def test_adjacent_equal_speaker_runs_merge(self) -> None:
        segments = [_segment("abcdef")]
        edits = [
            _speaker_edit(char_start=0, char_end=3, original="abc"),
            _speaker_edit(char_start=3, char_end=6, original="def"),
        ]

        corrected, _, _ = apply_corrections_and_speaker_edits(segments, [], edits)

        assert corrected[0]["speaker"] == "SPEAKER_01"
        assert "speaker_runs" not in corrected[0]

    def test_mismatched_speaker_edits_are_skipped(self) -> None:
        segments = [_segment("Hej världen.")]
        wrong_speaker = _speaker_edit(original_speaker="SPEAKER_05")
        wrong_text = _speaker_edit(char_start=0, char_end=3, original="Nej")
        out_of_range = _speaker_edit(segment_index=7)

        corrected, _, skipped = apply_corrections_and_speaker_edits(
            segments, [], [wrong_speaker, wrong_text, out_of_range]
        )

        assert corrected[0]["speaker"] == "SPEAKER_00"
        assert "speaker_runs" not in corrected[0]
        assert set(skipped) == {wrong_speaker, wrong_text, out_of_range}

    def test_speaker_edits_do_not_mutate_input_segments(self) -> None:
        segments = [_segment("Hej världen.")]

        corrected, _, _ = apply_corrections_and_speaker_edits(
            segments, [], [_speaker_edit()]
        )

        assert segments[0]["speaker"] == "SPEAKER_00"
        assert corrected[0]["speaker"] == "SPEAKER_01"


_PREFIX_1 = "[00:00:00 - 00:00:04] "
_PREFIX_2 = "[00:00:04 - 00:00:08] "


class TestApplyToRenderedTranscript:
    def _segments(self) -> list[dict]:
        return [
            _segment("Vi frågade sugary om planen."),
            _segment("sugary svarade direkt.", speaker="SPEAKER_01"),
        ]

    def _rendered(self) -> str:
        return "\n".join(
            [
                "## Del 1",
                f"{_PREFIX_1}SPEAKER_00: Vi frågade sugary om planen.",
                "",
                f"{_PREFIX_2}SPEAKER_01: sugary svarade direkt.",
            ]
        )

    def test_patches_single_run_lines_in_place(self) -> None:
        occurrences = [
            _occurrence(
                char_start=11, char_end=17, original="sugary", corrected="Çagri"
            )
        ]
        edits = [
            _speaker_edit(
                segment_index=1,
                original_speaker="SPEAKER_01",
                speaker="SPEAKER_03",
            )
        ]

        patched = apply_to_rendered_transcript(
            self._rendered(), self._segments(), occurrences, edits
        )

        assert patched == "\n".join(
            [
                "## Del 1",
                f"{_PREFIX_1}SPEAKER_00: Vi frågade Çagri om planen.",
                "",
                f"{_PREFIX_2}SPEAKER_03: sugary svarade direkt.",
            ]
        )

    def test_splits_a_line_per_run_with_the_same_prefix(self) -> None:
        edits = [_speaker_edit(char_start=18, char_end=28, original="om planen.")]

        patched = apply_to_rendered_transcript(
            self._rendered(), self._segments(), [], edits
        )

        assert patched == "\n".join(
            [
                "## Del 1",
                f"{_PREFIX_1}SPEAKER_00: Vi frågade sugary",
                f"{_PREFIX_1}SPEAKER_01: om planen.",
                "",
                f"{_PREFIX_2}SPEAKER_01: sugary svarade direkt.",
            ]
        )

    def test_returns_none_when_a_line_was_hand_edited(self) -> None:
        rendered = self._rendered().replace("svarade", "sa")

        assert (
            apply_to_rendered_transcript(
                rendered, self._segments(), [], [_speaker_edit()]
            )
            is None
        )

    def test_returns_none_when_line_count_does_not_match(self) -> None:
        rendered = f"{_PREFIX_1}SPEAKER_00: Vi frågade sugary om planen."

        assert (
            apply_to_rendered_transcript(
                rendered, self._segments(), [], [_speaker_edit()]
            )
            is None
        )


class TestSortSpeakerEdits:
    def test_whole_segment_sorts_before_spans(self) -> None:
        span = _speaker_edit(char_start=0, char_end=3, original="abc")
        whole = _speaker_edit()
        later_segment = _speaker_edit(segment_index=1, original_speaker="SPEAKER_01")

        assert sort_speaker_edits([later_segment, span, whole]) == [
            whole,
            span,
            later_segment,
        ]
