from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    ProposalIntentArgumentError,
    SemanticStepIntent,
    parse_create_flow_intent_arguments,
)
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
            _field("beslut", field_type="array", item_fields=None),
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
    # Backend-owned field drafts use the typed default. Provider output is
    # separately constrained by the create tool schema.
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


def test_depth_four_nesting_validates_at_the_step_boundary() -> None:
    nested = _field(
        "djup",
        field_type="object",
        fields=[
            _field(
                "niva2",
                field_type="array",
                item_fields=[
                    _field(
                        "niva3",
                        field_type="object",
                        fields=[_field("niva4")],
                    )
                ],
            )
        ],
    )

    step = SemanticStepIntent.model_validate(
        {
            "name": "Extrahera",
            "instructions": "Extrahera djupa fält.",
            "output_type": "json",
            "output_fields": [nested],
        }
    )

    assert step.output_fields is not None
    assert step.output_fields[0].fields is not None
    assert step.output_fields[0].fields[0].item_fields is not None
    assert step.output_fields[0].fields[0].item_fields[0].fields is not None
    assert step.output_fields[0].fields[0].item_fields[0].fields[0].name == "niva4"


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
    with pytest.raises(StructuredFieldAdmissionError, match="non-empty item_fields"):
        normalize_structured_field_list(
            [_field("tom_lista", field_type="array", item_fields=[])]
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
                        fields=[
                            _field(
                                "stycke",
                                field_type="object",
                                fields=[_field("text")],
                            )
                        ],
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
    assert (
        "sections.arendet.underavsnitt.stycke.text: structured field nesting "
        "depth cannot exceed 4;" in message
    )


def test_non_ascii_field_names_fold_instead_of_rejecting() -> None:
    # Identity is folded, wording is the author's: "åtgärder" folds to a
    # valid identifier instead of costing a repair round (2026-08-06
    # checkpoint: two parse rejections for exactly this).
    step = SemanticStepIntent.model_validate(
        {
            "name": "Strukturera åtgärder",
            "instructions": "Lista åtgärder ur underlaget.",
            "output_type": "json",
            "output_fields": [
                _field("åtgärder"),
                _field("öppna frågor"),
            ],
        }
    )
    assert [field.name for field in step.output_fields or []] == [
        "atgarder",
        "oppna_fragor",
    ]


@pytest.mark.parametrize(
    "output_fields",
    [
        [_field("åtgärder"), _field("atgarder")],
        [
            _field(
                "grupp",
                field_type="object",
                fields=[_field("Öppna frågor"), _field("oppna_fragor")],
            )
        ],
        [
            _field(
                "poster",
                field_type="array",
                item_fields=[_field("Beslut"), _field("beslut")],
            )
        ],
    ],
)
def test_sibling_names_must_be_unique_after_recursive_folding(
    output_fields: list[dict[str, object]],
) -> None:
    with pytest.raises(PydanticValidationError, match="unique among siblings"):
        SemanticStepIntent.model_validate(
            {
                "name": "Strukturera",
                "instructions": "Strukturera underlaget.",
                "output_type": "json",
                "output_fields": output_fields,
            }
        )


def test_unfoldable_field_names_still_reject() -> None:
    with pytest.raises(PydanticValidationError, match="ASCII identifiers"):
        SemanticStepIntent.model_validate(
            {
                "name": "Strukturera",
                "instructions": "Strukturera underlaget.",
                "output_type": "json",
                "output_fields": [_field("123")],
            }
        )


def test_object_shape_rejection_names_the_field() -> None:
    with pytest.raises(PydanticValidationError, match="tom_grupp"):
        SemanticStepIntent.model_validate(
            {
                "name": "Strukturera",
                "instructions": "Strukturera underlaget.",
                "output_type": "json",
                "output_fields": [_field("tom_grupp", field_type="object")],
            }
        )


def test_leading_field_draft_still_fails_visibly() -> None:
    with pytest.raises(ProposalIntentArgumentError, match="instructions"):
        parse_create_flow_intent_arguments(
            {
                "flow_name": "Beslutsunderlag",
                "plan_rationale": "Strukturera underlaget.",
                "steps": [_field("risks")],
            }
        )


def test_stray_step_keys_on_fields_reject_the_whole_list() -> None:
    with pytest.raises(StructuredFieldAdmissionError, match="model_ref"):
        normalize_structured_field_list([_field("titel", model_ref="model.gpt-test")])


def test_non_field_list_in_steps_still_fails_visibly() -> None:
    with pytest.raises(ProposalIntentArgumentError):
        parse_create_flow_intent_arguments(
            {
                "flow_name": "Beslutsunderlag",
                "plan_rationale": "Strukturera underlaget.",
                "steps": [
                    {
                        "name": "Strukturera",
                        "instructions": "Strukturera underlaget.",
                    },
                    ["not a field draft"],
                ],
            }
        )


def test_missing_field_type_rejects_the_whole_list() -> None:
    with pytest.raises(StructuredFieldAdmissionError, match="field_type"):
        normalize_structured_field_list(
            [{"name": "titel", "description": "Dokumentets titel."}]
        )
