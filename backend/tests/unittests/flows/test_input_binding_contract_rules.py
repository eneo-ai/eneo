from __future__ import annotations

import pytest

from eneo.flows.input_binding_contract_rules import (
    InputBindingContractError,
    SourceRefBinding,
    dedupe_source_refs,
    effective_question_binding,
    field_refs_cover_whole_structured_object,
    input_contract_conflicts_with_question_binding,
    lower_source_refs_to_question_binding,
    question_binding,
    source_ref_bindings,
    unsupported_input_binding_key,
)


def test_question_binding_returns_original_non_empty_question() -> None:
    assert question_binding({"question": "  {{ step_a.output.text }}  "}) == (
        "  {{ step_a.output.text }}  "
    )


def test_question_binding_ignores_missing_blank_or_non_string_values() -> None:
    assert question_binding(None) is None
    assert question_binding({}) is None
    assert question_binding({"question": "  "}) is None
    assert question_binding({"question": 42}) is None


def test_effective_question_binding_lowers_authoring_source_refs() -> None:
    assert (
        effective_question_binding(
            {
                "source_refs": [
                    {
                        "step_ref": "step_a",
                        "output": "structured",
                        "field_path": "decisions",
                        "label": "Beslut",
                    }
                ]
            }
        )
        == "Beslut: {{ step_a.output.structured.decisions }}"
    )


def test_input_contract_conflicts_only_when_question_binding_supplies_input() -> None:
    contract = {"type": "object"}

    assert input_contract_conflicts_with_question_binding(
        input_bindings={"question": "{{ step_a.output.structured }}"},
        input_contract=contract,
    )
    assert not input_contract_conflicts_with_question_binding(
        input_bindings={"question": "  "},
        input_contract=contract,
    )
    assert not input_contract_conflicts_with_question_binding(
        input_bindings={"question": "{{ step_a.output.structured }}"},
        input_contract=None,
    )
    assert input_contract_conflicts_with_question_binding(
        input_bindings={
            "source_refs": [{"step_ref": "step_a", "output": "structured"}]
        },
        input_contract=contract,
    )


def test_field_refs_cover_whole_structured_object_requires_broad_top_level_coverage() -> (
    None
):
    property_names = {"summary", "details", "decision", "metadata.created_at"}

    assert field_refs_cover_whole_structured_object(
        field_paths={"summary", "details"},
        property_names=property_names,
    )
    assert not field_refs_cover_whole_structured_object(
        field_paths={"summary"},
        property_names=property_names,
    )
    assert not field_refs_cover_whole_structured_object(
        field_paths={"metadata.created_at", "unknown"},
        property_names=property_names,
    )


def test_source_refs_lower_to_question_binding() -> None:
    assert lower_source_refs_to_question_binding(
        {
            "question": "Draft intro",
            "source_refs": [
                {
                    "step_ref": "step_a",
                    "output": "text",
                    "label": "Source material",
                },
                {
                    "step_ref": "step_b",
                    "output": "structured",
                    "field_path": "decisions",
                },
                {
                    "step_ref": "step_c",
                    "output": "structured",
                },
            ],
        }
    ) == {
        "question": (
            "Draft intro\n\n"
            "Source material: {{ step_a.output.text }}\n\n"
            "{{ step_b.output.structured.decisions }}\n\n"
            "{{ step_c.output.structured }}"
        )
    }


def test_source_refs_lower_without_existing_question() -> None:
    assert lower_source_refs_to_question_binding(
        {
            "source_refs": [
                {
                    "step_ref": "step_a",
                    "output": "structured",
                    "field_path": "summary.notes",
                    "label": "Structured notes",
                }
            ],
        }
    ) == {
        "question": ("Structured notes: {{ step_a.output.structured.summary.notes }}")
    }


def test_source_refs_runtime_lowering_tolerates_duplicate_refs() -> None:
    assert lower_source_refs_to_question_binding(
        {
            "source_refs": [
                {"step_ref": "step_a", "output": "text"},
                {"step_ref": "step_a", "output": "text", "label": "Step 1 output"},
            ],
        }
    ) == {
        "question": (
            "{{ step_a.output.text }}\n\nStep 1 output: {{ step_a.output.text }}"
        )
    }


def test_dedupe_source_refs_prefers_labeled_ref_and_first_labeled_tie() -> None:
    assert [
        ref.binding_payload()
        for ref in dedupe_source_refs(
            (
                SourceRefBinding(step_ref="step_a", output="text"),
                SourceRefBinding(
                    step_ref="step_a", output="text", label="Step 1 output"
                ),
                SourceRefBinding(
                    step_ref="step_a", output="text", label="Duplicate label"
                ),
            )
        )
    ] == [{"step_ref": "step_a", "output": "text", "label": "Step 1 output"}]


def test_source_refs_empty_list_lowers_to_absent_binding() -> None:
    assert lower_source_refs_to_question_binding({"source_refs": []}) is None


@pytest.mark.parametrize(
    "input_bindings",
    [
        {"source_refs": {}},
        {"source_refs": ["step_a"]},
        {"source_refs": [{"step_ref": "step_a", "output": "json"}]},
        {
            "source_refs": [
                {"step_ref": "step_a", "output": "text", "field_path": "summary"}
            ]
        },
        {
            "source_refs": [
                {"step_ref": "step_a", "output": "text", "label": "{{ bad }}"}
            ]
        },
        {"source_refs": [{"step_ref": "step_a", "output": "text", "unexpected": True}]},
    ],
)
def test_source_refs_reject_invalid_shape(input_bindings: object) -> None:
    with pytest.raises(InputBindingContractError):
        source_ref_bindings(input_bindings)


def test_runtime_binding_key_validation_accepts_typed_source_refs() -> None:
    assert (
        unsupported_input_binding_key({"question": "{{ step_a.output.text }}"}) is None
    )
    assert unsupported_input_binding_key({"source_refs": []}) is None
    assert unsupported_input_binding_key({1: "bad"}) == "1"
