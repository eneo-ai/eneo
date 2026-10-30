from __future__ import annotations

import pytest

from eneo.flows.flow_authoring_variable_rewriting import (
    renumber_input_binding_aliases,
    renumber_step_aliases,
)
from tests.unittests.flows.source_ref_runtime_test_support import (
    runtime_source_ref_text,
)

_MOVED = {1: 2, 2: 3}


def test_only_the_head_of_a_template_expression_is_an_alias() -> None:
    text = (
        "{{step_1.output.text}} {{ step_2 }} {{ form.step_1 }} step_1 {{ step_10.a }}"
    )

    assert renumber_step_aliases(text, _MOVED) == (
        "{{step_2.output.text}} {{ step_3 }} {{ form.step_1 }} step_1 {{ step_10.a }}"
    )


def test_a_step_that_did_not_move_and_an_empty_mapping_change_nothing() -> None:
    text = "{{ step_3.output.text }}"

    assert renumber_step_aliases(text, _MOVED) == text
    assert renumber_step_aliases("{{ step_1 }}", {}) == "{{ step_1 }}"


def test_every_alias_moves_by_the_old_position_not_one_after_another() -> None:
    assert renumber_step_aliases("{{ step_1 }}{{ step_2 }}", _MOVED) == (
        "{{ step_2 }}{{ step_3 }}"
    )


def test_containers_are_walked_and_other_values_are_left_as_they_are() -> None:
    value = {
        "a": ["{{step_1.x}}", {"b": "{{ step_2.y }}", "c": 1, "d": None}],
        "e": True,
    }

    assert renumber_step_aliases(value, _MOVED) == {
        "a": ["{{step_2.x}}", {"b": "{{ step_3.y }}", "c": 1, "d": None}],
        "e": True,
    }


def test_the_step_ref_of_a_source_ref_moves_with_its_step() -> None:
    bindings = {
        "question": "{{step_1.output.text}}",
        "source_refs": [
            {"step_ref": "step_1", "field": "svar"},
            {"step_ref": "step_9"},
            "step_1",
            {"step_ref": "existing_step_1"},
        ],
    }

    assert renumber_input_binding_aliases(bindings, _MOVED) == {
        "question": "{{step_2.output.text}}",
        "source_refs": [
            {"step_ref": "step_2", "field": "svar"},
            {"step_ref": "step_9"},
            "step_1",
            {"step_ref": "existing_step_1"},
        ],
    }
    assert bindings["source_refs"][0] == {"step_ref": "step_1", "field": "svar"}


def test_bindings_that_are_absent_stay_absent() -> None:
    assert renumber_input_binding_aliases(None, _MOVED) is None


@pytest.mark.parametrize(
    "text",
    [
        "{{ step_02.output.text }}",
        "{{ step_\u0662.output.text }}",
        "{{ step_\u00b2.output.text }}",
        "{{ step_2.output.text }",
        "Läs {{ step_2.output.text",
        "{{ step_2x.output }}",
    ],
    ids=[
        "leading zero",
        "Arabic-Indic digit",
        "superscript digit",
        "unclosed",
        "unterminated",
        "suffix",
    ],
)
def test_what_the_runtime_does_not_read_as_an_alias_is_left_as_it_is(text: str) -> None:
    assert renumber_step_aliases(text, _MOVED) == text


def test_an_alias_the_runtime_reads_with_spaces_around_its_head_is_renumbered() -> None:
    assert renumber_step_aliases("{{step_2 .output.text}}", _MOVED) == (
        "{{step_3 .output.text}}"
    )


@pytest.mark.parametrize(
    "step_ref", ["step_2", "step_02", "step_\u0662", "step_\u0660\u0662", "step_\uff12"]
)
def test_a_source_ref_the_runtime_reads_as_a_step_moves_with_it(step_ref: str) -> None:
    # The runtime reads the step number of a source ref in any script and with
    # leading zeros; a moved producer's ref is written back as `step_N`.
    bindings = {"source_refs": [{"step_ref": step_ref, "output": "text"}]}

    renumbered = renumber_input_binding_aliases(bindings, {2: 3})

    assert renumbered == {"source_refs": [{"step_ref": "step_3", "output": "text"}]}
    assert runtime_source_ref_text(
        renumbered, reader_order=4, text_by_order={3: "moved"}
    ) == ("moved")


@pytest.mark.parametrize(
    "step_ref",
    ["step_\u00b2", "step_", "step_2x", "Step_2", "existing_step_2", " step_2"],
)
def test_a_source_ref_the_runtime_does_not_read_as_a_step_keeps_its_step_ref(
    step_ref: str,
) -> None:
    bindings = {"source_refs": [{"step_ref": step_ref}]}

    assert renumber_input_binding_aliases(bindings, {2: 3}) == bindings


def test_the_alias_owner_reads_exactly_the_names_the_runtime_gives_steps() -> None:
    from eneo.flows.variable_resolver import (
        runtime_step_alias,
        runtime_step_alias_order,
    )

    assert [
        runtime_step_alias_order(name)
        for name in ("step_1", "step_12", "step_01", "step_\u0662", "step_", "steps_1")
    ] == [1, 12, None, None, None, None]
    assert runtime_step_alias(7) == "step_7"
