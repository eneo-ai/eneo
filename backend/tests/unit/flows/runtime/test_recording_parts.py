from __future__ import annotations

import pytest

from eneo.files.transcriber import TranscribedAudio
from eneo.flows.runtime.recording_parts import (
    PartBounds,
    RecordingSplitError,
    join_part_windows,
    split_recording,
)
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    EmptyTranscriptionInterval,
    TranscriptSegment,
    TranscriptWord,
)

# Two parts of one recording: 0-10 s and 10-25 s on the recording's timeline.
BOUNDS = (PartBounds(start=0.0, duration=10.0), PartBounds(start=10.0, duration=15.0))


def _words(*items: tuple[str, float, float]) -> tuple[TranscriptWord, ...]:
    return tuple(TranscriptWord(word=w, start=s, end=e) for w, s, e in items)


def _labelled(*segments: TranscriptSegment, **extra) -> TranscribedAudio:
    return TranscribedAudio(
        text="",
        duration_seconds=25.0,
        transcript_segments=segments,
        diarization="external",
        alignment="forced",
        **extra,
    )


def test_one_voice_keeps_one_label_in_both_parts():
    anna_first = TranscriptSegment(
        "Hej alla.",
        1.0,
        3.0,
        "SPEAKER_00",
        _words(("Hej", 1.0, 1.5), ("alla.", 1.6, 3.0)),
    )
    anna_later = TranscriptSegment(
        "Tack.", 12.0, 13.0, "SPEAKER_00", _words(("Tack.", 12.0, 13.0))
    )

    first, second = split_recording(_labelled(anna_first, anna_later), BOUNDS)

    assert [s.speaker for s in first.transcript_segments] == ["SPEAKER_00"]
    assert [s.speaker for s in second.transcript_segments] == ["SPEAKER_00"]
    assert second.transcript_segments[0].start == 2.0
    assert second.transcript_segments[0].words[0].start == 2.0
    assert (first.duration_seconds, second.duration_seconds) == (10.0, 15.0)


def test_a_segment_across_the_seam_splits_by_its_words():
    across = TranscriptSegment(
        "Vi ses snart igen.",
        8.0,
        11.5,
        "SPEAKER_01",
        _words(
            ("Vi", 8.0, 8.4),
            ("ses", 8.5, 9.9),
            ("snart", 10.2, 10.8),
            ("igen.", 10.9, 11.5),
        ),
        speaker_attribution="clean",
    )

    first, second = split_recording(_labelled(across), BOUNDS)

    (head,) = first.transcript_segments
    (tail,) = second.transcript_segments
    assert (head.text, head.start, head.end) == ("Vi ses", 8.0, 9.9)
    assert (tail.text, tail.start, tail.end) == ("snart igen.", pytest.approx(0.2), 1.5)
    assert head.speaker == tail.speaker == "SPEAKER_01"
    assert head.speaker_attribution == tail.speaker_attribution == "clean"


def test_a_word_straddling_the_seam_stays_whole_in_the_part_it_starts_in():
    straddling = TranscriptSegment(
        "Budgeten", 9.6, 10.4, "SPEAKER_00", _words(("Budgeten", 9.6, 10.4))
    )

    first, second = split_recording(_labelled(straddling), BOUNDS)

    (only,) = first.transcript_segments
    assert (only.start, only.end, only.words[0].end) == (9.6, 10.0, 10.0)
    assert second.transcript_segments == ()


def test_a_wordless_segment_inside_one_part_is_kept_whole():
    wordless = TranscriptSegment("Nästa punkt.", 14.0, 16.0, "SPEAKER_02")

    first, second = split_recording(_labelled(wordless), BOUNDS)

    assert first.transcript_segments == ()
    assert second.transcript_segments == (
        TranscriptSegment("Nästa punkt.", 4.0, 6.0, "SPEAKER_02"),
    )


def test_a_wordless_segment_across_the_seam_is_refused():
    wordless = TranscriptSegment("Nästa punkt.", 9.0, 12.0, "SPEAKER_02")

    with pytest.raises(RecordingSplitError):
        split_recording(_labelled(wordless), BOUNDS)


def test_words_that_do_not_spell_the_split_segment_are_refused():
    mismatched = TranscriptSegment(
        "Vi ses snart.",
        9.0,
        11.0,
        "SPEAKER_00",
        _words(("Vi", 9.0, 9.5), ("snart", 10.2, 11.0)),
    )

    with pytest.raises(RecordingSplitError):
        split_recording(_labelled(mismatched), BOUNDS)


def test_an_overlap_is_clipped_into_every_part_it_touches():
    review = {
        "version": 1,
        "overlap_detection": "available",
        "overlaps": [
            {"id": "ov-1", "start": 9.0, "end": 11.0, "detected_speaker_count": 2},
            {"id": "ov-2", "start": 20.0, "end": 21.0, "detected_speaker_count": 2},
        ],
    }

    first, second = split_recording(_labelled(speaker_review=review), BOUNDS)

    assert first.speaker_review["overlaps"] == [
        {"id": "ov-1", "start": 9.0, "end": 10.0, "detected_speaker_count": 2}
    ]
    assert second.speaker_review["overlaps"] == [
        {"id": "ov-1", "start": 0.0, "end": 1.0, "detected_speaker_count": 2},
        {"id": "ov-2", "start": 10.0, "end": 11.0, "detected_speaker_count": 2},
    ]
    assert first.speaker_review["overlap_detection"] == "available"


def test_empty_intervals_follow_their_part():
    labelled = _labelled(
        empty_intervals=(EmptyTranscriptionInterval(5.0, 12.0),),
    )

    first, second = split_recording(labelled, BOUNDS)

    assert first.empty_intervals == (EmptyTranscriptionInterval(5.0, 10.0),)
    assert second.empty_intervals == (EmptyTranscriptionInterval(0.0, 2.0),)


def test_part_windows_join_on_the_recording_timeline():
    first = TranscribedAudio(
        text="a",
        duration_seconds=10.0,
        segments=(TranscriptSegment("a", 0.0, 10.0),),
    )
    second = TranscribedAudio(
        text="b",
        duration_seconds=15.0,
        segments=(TranscriptSegment("b", 0.0, 5.0),),
        empty_intervals=(EmptyTranscriptionInterval(5.0, 15.0),),
    )

    joined = join_part_windows((first, second), BOUNDS)

    assert joined.segments == (
        TranscriptSegment("a", 0.0, 10.0),
        TranscriptSegment("b", 10.0, 15.0),
    )
    assert joined.empty_intervals == (EmptyTranscriptionInterval(15.0, 25.0),)
    assert joined.duration_seconds == 25.0
    assert joined.text == "a\n\nb"


def test_part_windows_past_their_decoded_part_are_refused():
    drifted = TranscribedAudio(
        text="a",
        duration_seconds=10.0,
        segments=(TranscriptSegment("a", 0.0, 10.5),),
    )
    second = TranscribedAudio(text="", duration_seconds=15.0, segments=())

    with pytest.raises(RecordingSplitError):
        join_part_windows((drifted, second), BOUNDS)


def test_labelled_text_without_segments_is_refused():
    labelled = TranscribedAudio(
        text="[00:00:01 - 00:00:02] SPEAKER_00: Hej.",
        duration_seconds=25.0,
        diarization="external",
    )

    with pytest.raises(RecordingSplitError):
        split_recording(labelled, BOUNDS)


def test_a_seam_crossing_segment_with_partial_words_is_refused():
    # The service may time only some words; they must not decide where all the text goes.
    partial = TranscriptSegment(
        "Vi ses snart igen.", 8.0, 11.5, "SPEAKER_00", _words(("Vi", 8.0, 8.4))
    )

    with pytest.raises(RecordingSplitError):
        split_recording(_labelled(partial), BOUNDS)


def test_partial_words_inside_one_part_keep_the_whole_segment():
    partial = TranscriptSegment(
        "Vi ses snart igen.", 11.0, 14.0, "SPEAKER_00", _words(("Vi", 11.0, 11.4))
    )

    _, second = split_recording(_labelled(partial), BOUNDS)

    assert second.transcript_segments[0].text == "Vi ses snart igen."
    assert (second.transcript_segments[0].start, second.transcript_segments[0].end) == (
        1.0,
        4.0,
    )


def test_a_short_wordless_segment_just_after_the_seam_stays_in_its_part():
    short = TranscriptSegment("Ja.", 10.0, 10.03, "SPEAKER_01")

    first, second = split_recording(_labelled(short), BOUNDS)

    assert first.transcript_segments == ()
    assert second.transcript_segments[0].start == 0.0


@pytest.mark.parametrize(
    "segment",
    [
        TranscriptSegment("Sent.", 24.0, 26.0, "SPEAKER_00"),
        TranscriptSegment("Baklänges.", 5.0, 4.0, "SPEAKER_00"),
        TranscriptSegment(
            "Hej.", 1.0, 2.0, "SPEAKER_00", _words(("Hej.", float("nan"), 2.0))
        ),
    ],
)
def test_times_outside_the_recording_are_refused(segment):
    with pytest.raises(RecordingSplitError):
        split_recording(_labelled(segment), BOUNDS)


@pytest.mark.parametrize(
    "segment",
    [
        # A word timed in the other part than the segment it belongs to.
        TranscriptSegment("Hej.", 1.0, 2.0, "SPEAKER_00", _words(("Hej.", 11.0, 12.0))),
        # Complete words across the seam, but out of time order.
        TranscriptSegment(
            "Vi ses.",
            9.0,
            11.0,
            "SPEAKER_00",
            _words(("Vi", 10.5, 11.0), ("ses.", 9.0, 9.5)),
        ),
    ],
)
def test_words_must_lie_in_their_segment_in_time_order(segment):
    with pytest.raises(RecordingSplitError):
        split_recording(_labelled(segment), BOUNDS)


def test_a_word_past_the_recording_is_refused_even_inside_its_segment():
    # The segment ends at the edge the tolerance allows; its word ends past it.
    edge = TranscriptSegment(
        "Slut.", 24.0, 25.05, "SPEAKER_00", _words(("Slut.", 24.0, 25.1))
    )

    with pytest.raises(RecordingSplitError):
        split_recording(_labelled(edge), BOUNDS)
