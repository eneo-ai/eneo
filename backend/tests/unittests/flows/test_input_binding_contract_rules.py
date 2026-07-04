from __future__ import annotations

from eneo.flows.input_binding_contract_rules import (
    input_contract_conflicts_with_question_binding,
    question_binding,
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


def test_unsupported_input_binding_key_allows_only_question_today() -> None:
    assert (
        unsupported_input_binding_key({"question": "{{ step_a.output.text }}"}) is None
    )
    assert unsupported_input_binding_key({"source_refs": []}) == "source_refs"
    assert unsupported_input_binding_key({1: "bad"}) == "1"
