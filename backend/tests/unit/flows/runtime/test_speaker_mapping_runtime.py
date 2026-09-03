from __future__ import annotations

import json

import pytest

from eneo.flows.runtime.speaker_mapping_runtime import (
    SPEAKER_MAPPING_INFER_INSTRUCTIONS,
    SPEAKER_MAPPING_INSTRUCTIONS,
    SpeakerMappingValidationError,
    build_speaker_mapping_question,
    mapping_to_names,
    resolve_participants,
    speaker_mapping_instructions,
    validate_speaker_mapping,
)

INVENTORY = [
    {"label": "SPEAKER_00", "file_index": 0, "line_count": 3, "samples": ["Hej"]},
    {"label": "SPEAKER_01", "file_index": 0, "line_count": 1, "samples": ["Tack"]},
]
PARTICIPANTS = ["Anna Svensson", "Bo Berg"]


def test_question_is_json_with_inventory_and_participants() -> None:
    payload = json.loads(
        build_speaker_mapping_question(inventory=INVENTORY, participants=PARTICIPANTS)
    )
    assert payload["participants"] == PARTICIPANTS
    assert [item["label"] for item in payload["speakers"]] == [
        "SPEAKER_00",
        "SPEAKER_01",
    ]
    assert payload["speakers"][0]["samples"] == ["Hej"]


def test_resolve_participants_reads_the_semantic_run_input() -> None:
    payload = {"deltagare": "Anna Svensson, Bo Berg", "transkribering": "..."}
    assert resolve_participants(payload, "deltagare") == PARTICIPANTS
    assert resolve_participants(payload, None) == []
    assert resolve_participants(None, "deltagare") == []


def test_max_speakers_comes_from_the_first_mapping_step() -> None:
    from types import SimpleNamespace

    from eneo.flows.runtime.speaker_mapping_runtime import resolve_max_speakers

    steps = [
        SimpleNamespace(output_mode="transcribe_only", output_config=None),
        SimpleNamespace(
            output_mode="speaker_mapping",
            output_config={"speaker_mapping": {"speaker_count_field": "antal"}},
        ),
    ]
    assert resolve_max_speakers(steps, {"antal": 3}) == 3
    assert resolve_max_speakers(steps, {"antal": ""}) is None
    assert resolve_max_speakers(steps[:1], {"antal": 3}) is None


def test_only_the_speaker_count_field_bounds_diarization() -> None:
    from types import SimpleNamespace

    from eneo.flows.runtime.speaker_mapping_runtime import resolve_max_speakers

    steps = [
        SimpleNamespace(
            output_mode="speaker_mapping",
            output_config={
                "speaker_mapping": {
                    "participants_field": "deltagare",
                    "speaker_count_field": "antal",
                }
            },
        )
    ]
    # Names are not a cap: an incomplete list must not merge unlisted voices.
    assert resolve_max_speakers(steps, {"deltagare": "Anna, Bo", "antal": 4}) == 4
    assert (
        resolve_max_speakers(steps, {"deltagare": ["Anna", "Bo"], "antal": ""}) is None
    )
    assert resolve_max_speakers(steps, {"deltagare": "Anna, Bo"}) is None
    assert resolve_max_speakers(steps, {"antal": "3"}) == 3
    assert resolve_max_speakers(steps, {"antal": 0}) is None
    assert resolve_max_speakers(steps, {"antal": True}) is None
    assert resolve_max_speakers(steps, {}) is None


def test_no_speaker_count_field_means_no_bound() -> None:
    from types import SimpleNamespace

    from eneo.flows.runtime.speaker_mapping_runtime import resolve_max_speakers

    steps = [
        SimpleNamespace(
            output_mode="speaker_mapping",
            output_config={"speaker_mapping": {"participants_field": "deltagare"}},
        )
    ]
    assert resolve_max_speakers(steps, {"deltagare": "Anna, Bo, Cid"}) is None


def test_validate_normalizes_and_orders_by_inventory() -> None:
    mapping = validate_speaker_mapping(
        {
            "speakers": [
                {"label": "SPEAKER_01", "name": " Bo Berg ", "confidence": "high"},
                {"label": "SPEAKER_00", "name": None, "confidence": "weird"},
            ]
        },
        inventory=INVENTORY,
        participants=PARTICIPANTS,
        allow_free_text=False,
    )
    assert mapping == {
        "speakers": [
            {"label": "SPEAKER_00", "name": None, "confidence": "low", "evidence": ""},
            {
                "label": "SPEAKER_01",
                "name": "Bo Berg",
                "confidence": "high",
                "evidence": "",
            },
        ]
    }
    assert mapping_to_names(mapping) == {"SPEAKER_01": "Bo Berg"}


@pytest.mark.parametrize(
    "structured",
    [
        "not an object",
        {"speakers": "x"},
        {"speakers": [{"label": "SPEAKER_00", "name": "Anna Svensson"}]},  # missing 01
        {
            "speakers": [
                {"label": "SPEAKER_00", "name": "Anna Svensson"},
                {"label": "SPEAKER_01", "name": "Anna Svensson"},
                {"label": "SPEAKER_09", "name": None},
            ]
        },
        {
            "speakers": [
                {"label": "SPEAKER_00", "name": "Anna Svensson"},
                {"label": "SPEAKER_01", "name": "Okänd Person"},
            ]
        },
    ],
)
def test_validate_rejects_bad_mappings(structured: object) -> None:
    with pytest.raises(SpeakerMappingValidationError):
        validate_speaker_mapping(
            structured,
            inventory=INVENTORY,
            participants=PARTICIPANTS,
            allow_free_text=False,
        )


def test_free_text_names_are_allowed_when_permitted() -> None:
    mapping = validate_speaker_mapping(
        {
            "speakers": [
                {"label": "SPEAKER_00", "name": "Okänd Person", "confidence": "low"},
                {"label": "SPEAKER_01", "name": None, "confidence": "low"},
            ]
        },
        inventory=INVENTORY,
        participants=PARTICIPANTS,
        allow_free_text=True,
    )
    assert mapping_to_names(mapping) == {"SPEAKER_00": "Okänd Person"}


def test_question_carries_the_opening_only_when_given() -> None:
    plain = json.loads(
        build_speaker_mapping_question(inventory=INVENTORY, participants=PARTICIPANTS)
    )
    assert "opening" not in plain

    with_opening = json.loads(
        build_speaker_mapping_question(
            inventory=INVENTORY,
            participants=[],
            opening=["SPEAKER_00: Hej Gunnar, jag heter Maria."],
        )
    )
    assert with_opening["opening"] == ["SPEAKER_00: Hej Gunnar, jag heter Maria."]


def test_instructions_switch_on_name_inference() -> None:
    fixed = speaker_mapping_instructions(infer_names=False)
    inferring = speaker_mapping_instructions(infer_names=True)
    assert fixed == SPEAKER_MAPPING_INSTRUCTIONS
    assert inferring == SPEAKER_MAPPING_INFER_INSTRUCTIONS
    assert "Never invent a name" in fixed
    assert "Never invent a name" not in inferring
    assert "participant list never" in inferring
