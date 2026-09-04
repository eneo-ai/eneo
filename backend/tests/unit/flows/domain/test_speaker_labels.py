from __future__ import annotations

from eneo.flows.domain.speaker_labels import (
    INVENTORY_SAMPLE_CHARS,
    OPENING_EXCERPT_CHARS,
    OPENING_EXCERPT_LINE_CHARS,
    OPENING_EXCERPT_LINES,
    apply_speaker_names,
    build_label_renumbering,
    build_opening_excerpt,
    build_speaker_inventory,
    parse_participants,
    renumber_segment_speakers,
    renumber_speaker_labels,
)

TRANSCRIPT = "\n".join(
    [
        "[00:00:00 - 00:00:04] SPEAKER_00: Hej och välkomna.",
        "[00:00:05 - 00:00:09] SPEAKER_01: Tack så mycket.",
        "[00:00:10 - 00:00:12] SPEAKER_00: Vi börjar.",
        "En rad utan talare.",
        "[00:00:13 - 00:00:15] SPEAKER_00: ",
    ]
)


def test_renumber_shifts_labels_by_offset_in_order_of_appearance() -> None:
    text, count = renumber_speaker_labels(TRANSCRIPT, offset=2)

    assert count == 2
    assert text.splitlines()[0].startswith("[00:00:00 - 00:00:04] SPEAKER_02:")
    assert text.splitlines()[1].startswith("[00:00:05 - 00:00:09] SPEAKER_03:")
    assert text.splitlines()[2].startswith("[00:00:10 - 00:00:12] SPEAKER_02:")
    assert text.splitlines()[3] == "En rad utan talare."


def test_inventory_counts_lines_and_keeps_short_samples() -> None:
    inventory = build_speaker_inventory(TRANSCRIPT, file_index=1, file_id="f1")

    assert [entry["label"] for entry in inventory] == ["SPEAKER_00", "SPEAKER_01"]
    first = inventory[0]
    assert first["file_index"] == 1 and first["file_id"] == "f1"
    assert first["line_count"] == 3
    # Empty lines are counted but not offered as samples.
    assert first["samples"] == ["Hej och välkomna.", "Vi börjar."]


def test_inventory_is_empty_without_labels() -> None:
    assert build_speaker_inventory("Bara text.\n## Del 1") == []


def test_apply_names_replaces_only_mapped_labels() -> None:
    renamed = apply_speaker_names(TRANSCRIPT, {"SPEAKER_00": "Anna Svensson"})

    lines = renamed.splitlines()
    assert lines[0] == "[00:00:00 - 00:00:04] Anna Svensson: Hej och välkomna."
    assert lines[1] == "[00:00:05 - 00:00:09] SPEAKER_01: Tack så mycket."
    assert lines[3] == "En rad utan talare."


def test_apply_names_ignores_empty_names() -> None:
    assert apply_speaker_names(TRANSCRIPT, {"SPEAKER_00": ""}) == TRANSCRIPT


def test_parse_participants_accepts_lists_and_delimited_text() -> None:
    assert parse_participants(["Anna", " Bo ", "Anna", 3]) == ["Anna", "Bo"]
    assert parse_participants("Anna Svensson, Bo Berg; Cecilia\nDavid") == [
        "Anna Svensson",
        "Bo Berg",
        "Cecilia",
        "David",
    ]
    assert parse_participants(None) == []
    assert parse_participants(42) == []


def test_label_renumbering_follows_text_order_and_applies_to_segments() -> None:
    from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
        TranscriptSegment,
    )

    text = "\n".join(
        [
            "[00:00:00 - 00:00:01] SPEAKER_01: Hej.",
            "[00:00:02 - 00:00:03] SPEAKER_00: Hallå.",
        ]
    )
    mapping = build_label_renumbering(text, 2)
    assert mapping == {"SPEAKER_01": "SPEAKER_02", "SPEAKER_00": "SPEAKER_03"}

    segments = renumber_segment_speakers(
        [
            TranscriptSegment("Hej.", 0.0, 1.0, speaker="SPEAKER_01"),
            TranscriptSegment("Hallå.", 2.0, 3.0, speaker="SPEAKER_00"),
            TranscriptSegment("(paus)", 3.0, 4.0, speaker=None),
            TranscriptSegment("?", 4.0, 5.0, speaker="SPEAKER_09"),
        ],
        mapping,
    )
    assert [segment.speaker for segment in segments] == [
        "SPEAKER_02",
        "SPEAKER_03",
        None,
        "SPEAKER_09",
    ]


def test_opening_excerpt_keeps_order_and_drops_timestamps_and_empty_lines() -> None:
    assert build_opening_excerpt(TRANSCRIPT) == [
        "SPEAKER_00: Hej och välkomna.",
        "SPEAKER_01: Tack så mycket.",
        "SPEAKER_00: Vi börjar.",
    ]
    assert build_opening_excerpt("Bara text.") == []


def test_opening_excerpt_is_bounded_by_lines_and_characters() -> None:
    many = "\n".join(
        f"[00:00:00 - 00:00:01] SPEAKER_00: rad {index}"
        for index in range(OPENING_EXCERPT_LINES + 10)
    )
    assert len(build_opening_excerpt(many)) == OPENING_EXCERPT_LINES

    long_line = "x" * (OPENING_EXCERPT_LINE_CHARS + 50)
    heavy = "\n".join(
        f"[00:00:00 - 00:00:01] SPEAKER_00: {long_line}"
        for _ in range(OPENING_EXCERPT_LINES)
    )
    excerpt = build_opening_excerpt(heavy)
    assert 0 < len(excerpt) < OPENING_EXCERPT_LINES
    assert sum(len(line) for line in excerpt) <= OPENING_EXCERPT_CHARS
    assert all(
        len(line) == len("SPEAKER_00: ") + OPENING_EXCERPT_LINE_CHARS
        for line in excerpt
    )


def test_opening_excerpt_keeps_the_handover_at_the_end_of_a_long_line() -> None:
    # A host's introduction runs well past an inventory sample before naming
    # the person they hand over to; the opening must still carry that cue.
    monologue = "Det är en knepig fråga. " * 12
    handover = "Fredrik Birging, du är på ett möte där satsningen presenteras idag."
    line = monologue + handover
    assert INVENTORY_SAMPLE_CHARS < len(line) <= OPENING_EXCERPT_LINE_CHARS
    transcript = "\n".join(
        [
            f"[00:00:00 - 00:00:20] SPEAKER_00: {line}",
            "[00:00:21 - 00:00:25] SPEAKER_01: Ja, jag står här i kommunhuset.",
        ]
    )
    excerpt = build_opening_excerpt(transcript)
    assert excerpt[0].endswith(handover)
    assert excerpt[1] == "SPEAKER_01: Ja, jag står här i kommunhuset."
