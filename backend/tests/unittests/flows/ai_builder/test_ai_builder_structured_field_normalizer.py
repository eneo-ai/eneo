from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from eneo.flows.ai_builder.ai_builder_proposal_intent import SemanticStepIntent
from eneo.flows.ai_builder.ai_builder_structured_field_normalizer import (
    StructuredFieldAdmissionError,
    normalize_structured_field_list,
)


def _field(name: str, **overrides: object) -> dict[str, object]:
    field: dict[str, object] = {
        "name": name,
        "field_type": "string",
        "description": f"{name} ur underlaget.",
        "required": True,
    }
    field.update(overrides)
    return field


def test_none_and_empty_list_admit_as_no_fields() -> None:
    assert normalize_structured_field_list(None) is None
    assert normalize_structured_field_list([]) is None


def test_canonical_fields_are_preserved_losslessly() -> None:
    admitted = normalize_structured_field_list(
        [
            _field("beslut", field_type="array", item_fields=[]),
            _field(
                "atgard",
                field_type="object",
                fields=[_field("ansvarig", required=False)],
            ),
        ]
    )

    assert admitted is not None
    assert [field["name"] for field in admitted] == ["beslut", "atgard"]
    assert admitted[0]["field_type"] == "array"
    assert admitted[1]["fields"][0]["required"] is False


def test_omitted_required_flag_admits_with_the_typed_default() -> None:
    # `required` has a canonical default on StructuredFieldDraft — omitting
    # it loses nothing and must not cost a repair round.
    field = _field("beslut")
    del field["required"]

    admitted = normalize_structured_field_list([field])

    assert admitted is not None
    assert admitted[0]["required"] is True


@pytest.mark.parametrize(
    ("payload", "expected_fragment"),
    [
        ("beslut", "must be an array"),
        (["beslut", "atgarder"], "output_fields[0]"),
        ({"beslut": {"field_type": "array"}}, "must be an array"),
        ([{"field_type": "string", "description": "Namnlöst."}], "name"),
        ([_field("beslut", field_type="integer")], "field_type"),
        ([{"name": "beslut", "field_type": "array"}], "description"),
        ([42], "field object"),
    ],
)
def test_lossy_shapes_reject_the_whole_list(
    payload: object,
    expected_fragment: str,
) -> None:
    with pytest.raises(StructuredFieldAdmissionError) as excinfo:
        normalize_structured_field_list(payload)
    message = str(excinfo.value)
    assert expected_fragment in message
    assert "No output_fields were accepted" in message


def test_over_depth_nesting_rejects_at_the_step_boundary() -> None:
    # Nothing downgrades over-deep structures anymore, so the step-level
    # depth invariant sees and rejects them as a repairable typed error.
    nested = _field(
        "djup",
        field_type="object",
        fields=[
            _field(
                "niva2",
                field_type="object",
                fields=[
                    _field(
                        "niva3",
                        field_type="object",
                        fields=[_field("niva4")],
                    )
                ],
            )
        ],
    )
    with pytest.raises(PydanticValidationError, match="depth"):
        SemanticStepIntent.model_validate(
            {
                "name": "Extrahera",
                "instructions": "Extrahera djupa fält.",
                "output_type": "json",
                "output_fields": [nested],
            }
        )


def test_one_malformed_item_rejects_valid_siblings_too() -> None:
    # Partial retention is what silently narrowed live contracts: the model
    # must resend the complete list, so the error names the decisive item.
    with pytest.raises(StructuredFieldAdmissionError) as excinfo:
        normalize_structured_field_list(
            [
                _field("beslut"),
                _field("atgarder", field_type="lista"),
                _field("ansvariga"),
            ]
        )
    message = str(excinfo.value)
    assert "output_fields[1].field_type" in message
    assert "Resend the complete output_fields list" in message


def test_container_shape_rules_are_enforced() -> None:
    with pytest.raises(
        StructuredFieldAdmissionError,
        match="declare nested fields",
    ):
        normalize_structured_field_list([_field("tom_grupp", field_type="object")])
    with pytest.raises(StructuredFieldAdmissionError, match="item_fields"):
        normalize_structured_field_list(
            [_field("skalar", item_fields=[_field("barn")])]
        )


def test_depth_rejection_names_the_offending_branch() -> None:
    # Flagship capture 2026-08-06: a five-attempt repair loop because the
    # depth error said only 'steps.1' — the model could not find which
    # branch to flatten. The error must name the exact path.
    nested = _field(
        "sections",
        field_type="object",
        fields=[
            _field(
                "arendet",
                field_type="object",
                fields=[
                    _field(
                        "underavsnitt",
                        field_type="object",
                        fields=[_field("text")],
                    )
                ],
            )
        ],
    )
    with pytest.raises(PydanticValidationError) as excinfo:
        SemanticStepIntent.model_validate(
            {
                "name": "Förbered innehåll",
                "instructions": "Förbered tjänsteskrivelsens avsnitt.",
                "output_type": "json",
                "output_fields": [nested],
            }
        )
    message = str(excinfo.value)
    assert "sections.arendet.underavsnitt" in message
    assert "cannot exceed" in message
