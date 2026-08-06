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


def test_misplaced_field_drafts_reattach_to_the_preceding_step() -> None:
    # Dominant parse-failure family of the 2026-08-06 checkpoint (12 of
    # 14 rejections): the model's JSON nesting slips and a whole field
    # list lands in `steps` after its producing step. A step never has
    # field_type, so the shape is unambiguous and admission reattaches
    # the drafts instead of burning a repair round.
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Beslutsunderlag",
            "plan_rationale": "Strukturera underlaget.",
            "steps": [
                {
                    "name": "Strukturera underlag",
                    "instructions": "Strukturera beslutsunderlaget.",
                    "output_type": "json",
                    "output_fields": [_field("decisions")],
                },
                _field(
                    "open_questions",
                    item_fields=[_field("question")],
                    field_type="array",
                ),
                _field("risks"),
            ],
        }
    )

    assert len(intent.steps) == 1
    assert [field.name for field in intent.steps[0].output_fields or []] == [
        "decisions",
        "open_questions",
        "risks",
    ]


def test_leading_field_draft_still_fails_visibly() -> None:
    with pytest.raises(ProposalIntentArgumentError, match="instructions"):
        parse_create_flow_intent_arguments(
            {
                "flow_name": "Beslutsunderlag",
                "plan_rationale": "Strukturera underlaget.",
                "steps": [_field("risks")],
            }
        )


def test_stray_step_keys_on_fields_are_dropped_not_fatal() -> None:
    # Live captures 2026-08-06 (flagship + hard_many_source): the model
    # sprinkles step-level model_ref into field objects, which used to
    # reject the whole output_fields list.
    step = SemanticStepIntent.model_validate(
        {
            "name": "Läs handlingar",
            "instructions": "Läs och strukturera varje handling.",
            "output_type": "json",
            "output_fields": [
                _field("titel", model_ref="model.gpt-test"),
            ],
        }
    )
    assert [field.name for field in step.output_fields or []] == ["titel"]


def test_step_level_assumptions_hoist_to_the_root() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Handlingsläsning",
            "plan_rationale": "Strukturera underlaget.",
            "assumptions": ["Root-antagande."],
            "steps": [
                {
                    "name": "Läs handlingar",
                    "instructions": "Läs och strukturera varje handling.",
                    "assumptions": ["Stegets antagande hör hemma i roten."],
                }
            ],
        }
    )
    assert intent.assumptions == [
        "Root-antagande.",
        "Stegets antagande hör hemma i roten.",
    ]


def test_nested_field_draft_list_in_steps_reattaches() -> None:
    # Regression run 2026-08-06: five rejections of "steps.N: Input should
    # be a valid dictionary" — the model nests a whole LIST of field drafts
    # in the steps array, not just a single draft.
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Beslutsunderlag",
            "plan_rationale": "Strukturera underlaget.",
            "steps": [
                {
                    "name": "Strukturera underlag",
                    "instructions": "Strukturera beslutsunderlaget.",
                    "output_type": "json",
                    "output_fields": [_field("decisions")],
                },
                [_field("open_questions"), _field("risks")],
            ],
        }
    )

    assert len(intent.steps) == 1
    assert [field.name for field in intent.steps[0].output_fields or []] == [
        "decisions",
        "open_questions",
        "risks",
    ]


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


def test_missing_field_type_infers_from_the_declared_shape() -> None:
    # Live capture 2026-08-06: the model omitted field_type on one field
    # of a long list, which rejected the whole list. A field's own shape
    # already states its type.
    step = SemanticStepIntent.model_validate(
        {
            "name": "Strukturera",
            "instructions": "Strukturera underlaget.",
            "output_type": "json",
            "output_fields": [
                {"name": "titel", "description": "Dokumentets titel."},
                {
                    "name": "poster",
                    "description": "Rader ur underlaget.",
                    "item_fields": [
                        {
                            "name": "rad",
                            "description": "En rad.",
                            "field_type": "string",
                        }
                    ],
                },
                {
                    "name": "metadata",
                    "description": "Metadata om dokumentet.",
                    "fields": [
                        {
                            "name": "datum",
                            "description": "Datum.",
                            "field_type": "string",
                        }
                    ],
                },
            ],
        }
    )

    types = {field.name: field.field_type for field in step.output_fields or []}
    assert types == {"titel": "string", "poster": "array", "metadata": "object"}
