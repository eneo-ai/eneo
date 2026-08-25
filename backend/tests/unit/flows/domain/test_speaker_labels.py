from __future__ import annotations

from eneo.flows.domain.speaker_labels import (
    apply_speaker_names,
    build_speaker_inventory,
    parse_participants,
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
