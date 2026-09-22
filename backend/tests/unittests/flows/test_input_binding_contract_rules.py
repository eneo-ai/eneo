from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from eneo.flows.input_binding_contract_rules import (
    InputBindingContractError,
    SourceRefBinding,
    dedupe_source_refs,
    derive_structured_projection_contract,
    effective_question_binding,
    input_contract_binding_conflict,
    item_template_field_names,
    lower_source_refs_to_question_binding,
    question_binding,
    source_ref_bindings,
    unsupported_input_binding_key,
)


def _wildcard_projection_case() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any]
]:
    projected: dict[str, Any] = {
        "type": "object",
        "properties": {
            "underlag": {
                "type": "object",
                "properties": {
                    "krav": {
                        "type": "object",
                        "properties": {
                            "uppgifter": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {"text": {"type": "string"}},
                                    "required": ["text"],
                                    "additionalProperties": True,
                                },
                            }
                        },
                        "required": ["uppgifter"],
                        "additionalProperties": False,
                    }
                },
                "required": ["krav"],
                "additionalProperties": False,
            }
        },
        "required": ["underlag"],
        "additionalProperties": False,
    }
    section = deepcopy(projected)
    section["properties"]["underlag"]["properties"]["krav"]["properties"][
        "uppgifter"
    ].update(minItems=1, maxItems=2, uniqueItems=True)
    source = {
        "type": "object",
        "properties": {"sektioner": {"type": "array", "items": section}},
        "required": ["sektioner"],
        "additionalProperties": False,
    }
    bindings = {
        "source_refs": [
            {
                "step_ref": "step_1",
                "output": "structured",
                "field_path": "sektioner.*.underlag.krav.uppgifter",
            }
        ]
    }
    return bindings, source, projected


def test_wildcard_projection_schema_uses_suffix_and_unconstrained_aggregate() -> None:
    bindings, source, projected = _wildcard_projection_case()

    assert (
        derive_structured_projection_contract(
            input_bindings=bindings,
            source_contracts_by_step_ref={"step_1": source},
        )
        == projected
    )


@pytest.mark.parametrize(
    "field_path", ["sektioner.*.underlag.*.uppgifter", "sektioner.*"]
)
def test_wildcard_projection_rejects_invalid_grammar(field_path: str) -> None:
    bindings, _, _ = _wildcard_projection_case()
    bindings["source_refs"][0]["field_path"] = field_path

    with pytest.raises(InputBindingContractError, match="field_path .* is absent"):
        source_ref_bindings(bindings)


@pytest.mark.parametrize("invalid_node", ["scalar_leaf", "object_leaf", "non_array"])
def test_wildcard_projection_rejects_non_array_schema(invalid_node: str) -> None:
    bindings, source, _ = _wildcard_projection_case()
    sections = source["properties"]["sektioner"]
    if invalid_node == "non_array":
        sections["type"] = "object"
    else:
        properties = sections["items"]["properties"]["underlag"]["properties"]["krav"][
            "properties"
        ]
        properties["uppgifter"] = {
            "type": "string" if invalid_node == "scalar_leaf" else "object"
        }

    with pytest.raises(InputBindingContractError, match="field_path .* is absent"):
        derive_structured_projection_contract(
            input_bindings=bindings,
            source_contracts_by_step_ref={"step_1": source},
        )


def test_wildcard_projection_rejects_suffix_destination_collision() -> None:
    bindings, source, _ = _wildcard_projection_case()
    bindings["source_refs"].append({**bindings["source_refs"][0], "step_ref": "step_2"})

    with pytest.raises(
        InputBindingContractError, match="path collision at 'underlag.krav.uppgifter'"
    ):
        derive_structured_projection_contract(
            input_bindings=bindings,
            source_contracts_by_step_ref={"step_1": source, "step_2": source},
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


def test_input_contract_binding_conflict_names_the_binding_owner() -> None:
    contract = {"type": "object"}

    assert (
        input_contract_binding_conflict(
            input_bindings={"question": "{{ step_a.output.structured }}"},
            input_contract=contract,
            input_type="json",
        )
        == "question"
    )
    assert (
        input_contract_binding_conflict(
            input_bindings={"question": "  "},
            input_contract=contract,
            input_type="json",
        )
        is None
    )
    assert (
        input_contract_binding_conflict(
            input_bindings={"question": "{{ step_a.output.structured }}"},
            input_contract=None,
            input_type="json",
        )
        is None
    )
    assert (
        input_contract_binding_conflict(
            input_bindings={
                "source_refs": [{"step_ref": "step_a", "output": "structured"}]
            },
            input_contract=contract,
            input_type="json",
        )
        is None
    )
    assert (
        input_contract_binding_conflict(
            input_bindings={"source_refs": [{"step_ref": "step_a", "output": "text"}]},
            input_contract=contract,
            input_type="json",
        )
        == "source_refs"
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


def test_dedupe_source_refs_keeps_distinct_item_templates() -> None:
    assert [
        ref.binding_payload()
        for ref in dedupe_source_refs(
            (
                SourceRefBinding(
                    step_ref="step_a",
                    output="structured",
                    field_path=("items",),
                    item_template="{title}",
                ),
                SourceRefBinding(
                    step_ref="step_a",
                    output="structured",
                    field_path=("items",),
                    item_template="{title}\n{body}",
                ),
            )
        )
    ] == [
        {
            "step_ref": "step_a",
            "output": "structured",
            "field_path": "items",
            "item_template": "{title}",
        },
        {
            "step_ref": "step_a",
            "output": "structured",
            "field_path": "items",
            "item_template": "{title}\n{body}",
        },
    ]


def test_source_ref_item_template_uses_single_brace_fields() -> None:
    refs = source_ref_bindings(
        {
            "source_refs": [
                {
                    "step_ref": "step_a",
                    "output": "structured",
                    "field_path": "source_sections",
                    "item_template": "## {section_title}\n\n{section_body}",
                }
            ]
        }
    )

    assert refs[0].item_template == "## {section_title}\n\n{section_body}"
    item_template = refs[0].item_template
    assert item_template is not None
    assert item_template_field_names(item_template) == (
        "section_title",
        "section_body",
    )


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
        {
            "source_refs": [
                {
                    "step_ref": "step_a",
                    "output": "structured",
                    "field_path": "summary.{{ bad }}",
                }
            ]
        },
        {
            "source_refs": [
                {
                    "step_ref": "step_a",
                    "output": "structured",
                    "item_template": "{{ bad }}",
                }
            ]
        },
        {
            "source_refs": [
                {
                    "step_ref": "step_a",
                    "output": "structured",
                    "item_template": "{bad.field}",
                }
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
