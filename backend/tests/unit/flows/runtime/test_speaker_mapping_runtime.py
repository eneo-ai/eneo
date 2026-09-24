from __future__ import annotations

import json

import pytest

from eneo.flows.domain.one_line_text import ONE_LINE_TEXT_MAX_CHARS
from eneo.flows.runtime.speaker_mapping_runtime import (
    SPEAKER_MAPPING_INFER_INSTRUCTIONS,
    SPEAKER_MAPPING_INSTRUCTIONS,
    SpeakerMappingValidationError,
    build_speaker_mapping_question,
    ground_speaker_mapping_proposal,
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
    assert resolve_participants(payload, "deltagare") == (PARTICIPANTS, True)
    assert resolve_participants(payload, None) == ([], False)
    assert resolve_participants(None, "deltagare") == ([], False)
    assert resolve_participants({"deltagare": ["x" * 121]}, "deltagare") == ([], True)


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


INVENTORY_NAMES = [
    {"label": "SPEAKER_00", "name": "Anna Svensson"},
    {"label": "SPEAKER_01", "name": None},
]


def test_a_speaker_split_off_in_review_can_be_named_or_left_out() -> None:
    named = validate_speaker_mapping(
        {"speakers": [*INVENTORY_NAMES, {"label": "SPEAKER_05", "name": "Eva Ek"}]},
        inventory=INVENTORY,
        participants=PARTICIPANTS,
        allow_free_text=True,
        split_labels=["SPEAKER_05", "SPEAKER_00"],
    )
    assert [entry["label"] for entry in named["speakers"]] == [
        "SPEAKER_00",
        "SPEAKER_01",
        "SPEAKER_05",
    ]
    assert mapping_to_names(named) == {
        "SPEAKER_00": "Anna Svensson",
        "SPEAKER_05": "Eva Ek",
    }
    unnamed = validate_speaker_mapping(
        {"speakers": INVENTORY_NAMES},
        inventory=INVENTORY,
        participants=PARTICIPANTS,
        allow_free_text=True,
        split_labels=["SPEAKER_05"],
    )
    assert [entry["label"] for entry in unnamed["speakers"]] == [
        "SPEAKER_00",
        "SPEAKER_01",
    ]


@pytest.mark.parametrize(
    "speakers",
    [
        [INVENTORY_NAMES[0], {"label": "SPEAKER_05", "name": "Eva Ek"}],
        [*INVENTORY_NAMES, {"label": "SPEAKER_09", "name": "Eva Ek"}],
        [
            *INVENTORY_NAMES,
            {"label": "SPEAKER_05", "name": "Eva Ek"},
            {"label": "SPEAKER_05", "name": None},
        ],
    ],
)
def test_a_split_label_keeps_the_inventory_rules(speakers) -> None:
    with pytest.raises(SpeakerMappingValidationError):
        validate_speaker_mapping(
            {"speakers": speakers},
            inventory=INVENTORY,
            participants=PARTICIPANTS,
            allow_free_text=True,
            split_labels=["SPEAKER_05"],
        )


@pytest.mark.parametrize(
    "name",
    [
        "Anna\nSvensson",
        "Anna\rSvensson",
        "Anna\tSvensson",
        "Anna\u2028Svensson",
        "Anna\u200bSvensson",
        "x" * (ONE_LINE_TEXT_MAX_CHARS + 1),
    ],
)
def test_a_speaker_name_is_one_short_line(name: str) -> None:
    with pytest.raises(SpeakerMappingValidationError, match="SPEAKER_00"):
        validate_speaker_mapping(
            {"speakers": [{**INVENTORY_NAMES[0], "name": name}, INVENTORY_NAMES[1]]},
            inventory=INVENTORY,
            participants=PARTICIPANTS,
            allow_free_text=True,
        )


@pytest.mark.parametrize(
    ("proposed", "kept"),
    [
        ("Anna\nSvensson", "Anna Svensson"),
        ("  Anna \t\u2028 Svensson\r\n", "Anna Svensson"),
        ("An\u200bna Svens\u0007son\ud800", "Anna Svensson"),
        ("y" * ONE_LINE_TEXT_MAX_CHARS, "y" * ONE_LINE_TEXT_MAX_CHARS),
        ("x" * (ONE_LINE_TEXT_MAX_CHARS + 1), None),
        ("\u200b\u0007 \n", None),
    ],
)
def test_a_model_proposed_name_is_cleaned_not_refused(
    proposed: str, kept: str | None
) -> None:
    mapping = validate_speaker_mapping(
        {"speakers": [{**INVENTORY_NAMES[0], "name": proposed}, INVENTORY_NAMES[1]]},
        inventory=INVENTORY,
        participants=PARTICIPANTS,
        allow_free_text=True,
        model_proposal=True,
    )
    assert mapping["speakers"][0]["name"] == kept


def test_a_speaker_name_at_the_bound_is_kept() -> None:
    name = "x" * ONE_LINE_TEXT_MAX_CHARS
    mapping = validate_speaker_mapping(
        {
            "speakers": [
                {**INVENTORY_NAMES[0], "name": f" {name}\n"},
                INVENTORY_NAMES[1],
            ]
        },
        inventory=INVENTORY,
        participants=PARTICIPANTS,
        allow_free_text=True,
    )
    assert mapping_to_names(mapping) == {"SPEAKER_00": name}


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
    assert "Never invent a name" in inferring
    assert "participant list never" in inferring


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Agne", "Agne"),
        ("agne", "agne"),
        ("Agne Hansson", None),
        ("Ibrahim Baylan", None),
        ("Agn", None),
        ("ansvarig politiker", None),
    ],
)
def test_proposals_require_names_or_roles_in_supplied_words(name, expected) -> None:
    proposal = {
        "speakers": [
            {
                "label": "SPEAKER_00",
                "name": name,
                "confidence": "high",
                # The model's own explanation cannot supply missing name evidence.
                "evidence": f'Introduces themselves as "{name}".',
            }
        ]
    }
    grounded = ground_speaker_mapping_proposal(
        proposal,
        inventory=[
            {
                "label": "SPEAKER_01",
                "samples": [
                    "Behåll den där, Agne.",
                    "Vi behöver en politisk överenskommelse om energi.",
                ],
            }
        ],
        participants=[],
    )
    assert grounded["speakers"][0]["name"] == expected
    assert proposal["speakers"][0]["name"] == name
    if expected is None:
        assert grounded["speakers"][0]["confidence"] == "low"
        assert grounded["speakers"][0]["evidence"] == ""


@pytest.mark.parametrize(
    ("name", "participants", "samples", "opening", "expected"),
    [
        ("Ibrahim Baylan", ["Ibrahim Baylan"], [], [], "Ibrahim Baylan"),
        ("Gunnar", [], ["Hej."], ["SPEAKER_01: Gunnar, välkommen hit."], "Gunnar"),
        (
            "socialsekreterare",
            [],
            ["Jag arbetar som socialsekreterare."],
            [],
            "socialsekreterare",
        ),
        ("Åsa", [], ["Jag heter A\u030asa."], [], "Åsa"),
        ("Ann", [], ["Anna säger hej."], [], None),
        ("Agne Hansson", [], ["Agne", "Hansson"], [], None),
        ("Ibrahim Baylan", [], [], [], None),
    ],
)
def test_proposal_grounding_sources_and_word_boundaries(
    name, participants, samples, opening, expected
) -> None:
    mapping = ground_speaker_mapping_proposal(
        {"speakers": [{"label": "SPEAKER_00", "name": name, "confidence": "high"}]},
        inventory=[{"label": "SPEAKER_00", "samples": samples}],
        participants=participants,
        opening=opening,
    )
    assert mapping["speakers"][0]["name"] == expected
