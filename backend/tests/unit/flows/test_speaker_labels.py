"""Speaker labels: renumbering across files, the mapping question and its answer."""

import json

import pytest

from eneo.files.transcript import TranscriptSegment
from eneo.flows.speaker_labels import (
    SpeakerMappingInvalid,
    build_opening_excerpt,
    build_speaker_inventory,
    build_speaker_mapping_question,
    format_clock,
    parse_participants,
    parse_speaker_mapping,
    render_segments,
    renumber_segment_speakers,
)


def _segments():
    return [
        {
            "file_index": 0,
            "start": 0.0,
            "end": 4.5,
            "speaker": "SPEAKER_00",
            "text": "Hej Anna.",
        },
        {
            "file_index": 0,
            "start": 4.5,
            "end": 9.0,
            "speaker": "SPEAKER_01",
            "text": "Hej.",
        },
        {
            "file_index": 0,
            "start": 9.0,
            "end": 12.0,
            "speaker": "SPEAKER_00",
            "text": "Vi börjar.",
        },
    ]


def test_labels_of_a_second_file_continue_after_the_first():
    first = [
        TranscriptSegment("a", 0, 1, "SPEAKER_00"),
        TranscriptSegment("b", 1, 2, "SPEAKER_01"),
    ]
    second = [
        TranscriptSegment("c", 0, 1, "SPEAKER_01"),
        TranscriptSegment("d", 1, 2, "SPEAKER_00"),
    ]
    renumbered, count = renumber_segment_speakers(first, 0)
    assert [s.speaker for s in renumbered] == ["SPEAKER_00", "SPEAKER_01"]
    assert count == 2
    renumbered, count = renumber_segment_speakers(second, count)
    # First appearance decides: the second file's SPEAKER_01 becomes 02.
    assert [s.speaker for s in renumbered] == ["SPEAKER_02", "SPEAKER_03"]
    assert count == 2


def test_inventory_and_opening_follow_first_appearance():
    inventory = build_speaker_inventory(_segments())
    assert [entry["label"] for entry in inventory] == ["SPEAKER_00", "SPEAKER_01"]
    assert inventory[0]["line_count"] == 2
    assert inventory[0]["samples"] == ["Hej Anna.", "Vi börjar."]
    assert build_opening_excerpt(_segments()) == [
        "SPEAKER_00: Hej Anna.",
        "SPEAKER_01: Hej.",
        "SPEAKER_00: Vi börjar.",
    ]


def test_the_question_is_frozen_json_with_the_opening_only_when_given():
    inventory = build_speaker_inventory(_segments())
    question = json.loads(
        build_speaker_mapping_question(inventory=inventory, participants=["Anna"])
    )
    assert question["participants"] == ["Anna"]
    assert "opening" not in question
    with_opening = json.loads(
        build_speaker_mapping_question(
            inventory=inventory, participants=[], opening=["SPEAKER_00: Hej Anna."]
        )
    )
    assert with_opening["opening"] == ["SPEAKER_00: Hej Anna."]


def test_participants_parse_from_free_text_or_lists():
    assert parse_participants("Anna, Erik; Anna\nMaria") == ["Anna", "Erik", "Maria"]
    assert parse_participants(["Anna", 3, " Erik "]) == ["Anna", "Erik"]
    assert parse_participants(None) == []


class TestParseSpeakerMapping:
    inventory = build_speaker_inventory(_segments())

    def test_names_from_the_participant_list_are_returned_as_listed(self):
        answer = json.dumps(
            {
                "speakers": [
                    {"label": "SPEAKER_00", "name": "anna", "confidence": "high"},
                    {"label": "SPEAKER_01", "name": "Okänd", "confidence": "low"},
                ]
            }
        )
        names = parse_speaker_mapping(
            answer,
            inventory=self.inventory,
            participants=["Anna"],
            allow_free_text=False,
        )
        # A name outside the list is not a name without free text.
        assert names == {"SPEAKER_00": "Anna", "SPEAKER_01": None}

    def test_free_text_names_are_kept_when_inference_is_on(self):
        answer = '```json\n{"speakers": [{"label": "SPEAKER_00", "name": null, "confidence": "low"}, {"label": "SPEAKER_01", "name": "handläggaren", "confidence": "medium", "evidence": "x"}]}\n```'
        names = parse_speaker_mapping(
            answer, inventory=self.inventory, participants=[], allow_free_text=True
        )
        assert names == {"SPEAKER_00": None, "SPEAKER_01": "handläggaren"}

    def test_a_missing_or_unknown_label_is_refused(self):
        with pytest.raises(SpeakerMappingInvalid):
            parse_speaker_mapping(
                '{"speakers": [{"label": "SPEAKER_00", "name": null, "confidence": "low"}]}',
                inventory=self.inventory,
                participants=[],
                allow_free_text=True,
            )
        with pytest.raises(SpeakerMappingInvalid):
            parse_speaker_mapping(
                "not json",
                inventory=self.inventory,
                participants=[],
                allow_free_text=True,
            )


def test_rendering_uses_names_and_clocks():
    assert format_clock(3725.9) == "01:02:05"
    text = render_segments(_segments(), {"SPEAKER_00": "Erik"})
    assert text.split("\n") == [
        "[00:00:00 - 00:00:04] Erik: Hej Anna.",
        "[00:00:04 - 00:00:09] SPEAKER_01: Hej.",
        "[00:00:09 - 00:00:12] Erik: Vi börjar.",
    ]
    assert render_segments([{"start": 0, "end": 300, "text": "plain"}]) == (
        "[00:00:00 - 00:05:00] plain"
    )
