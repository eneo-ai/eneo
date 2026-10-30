"""The contract one example answer implies, read as the editors read it."""

from __future__ import annotations

import json

import pytest

from eneo.flows.domain.contract_from_example import (
    EXAMPLE_MAX_CHARACTERS,
    ExampleProblemError,
    contract_from_example,
)


def test_every_field_of_the_example_becomes_a_required_field_of_its_type():
    reading = contract_from_example(
        json.dumps(
            {"beslut": "Bifall", "belopp": 4500, "klar": True, "datum": ["2026-01-02"]}
        )
    )
    assert reading.contract == {
        "type": "object",
        "properties": {
            "beslut": {"type": "string"},
            "belopp": {"type": "number"},
            "klar": {"type": "boolean"},
            "datum": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["beslut", "belopp", "klar", "datum"],
    }
    assert reading.notes == ()


def test_what_one_example_cannot_decide_is_noted():
    reading = contract_from_example('{"a": [], "b": null, "c": [1, "x"]}')
    assert reading.notes == ("empty_list", "mixed_list", "null_value")
    assert reading.contract["properties"]["b"] == {"type": ["string", "null"]}
    assert reading.contract["properties"]["a"] == {"type": "array"}
    assert reading.contract["properties"]["c"] == {
        "type": "array",
        "items": {"type": "number"},
    }


def test_a_field_a_later_step_cannot_refer_to_is_marked():
    reading = contract_from_example('{"a.b": 1, "ok": 2}')
    assert [(f.name, f.variable) for f in reading.fields] == [
        ("a.b", False),
        ("ok", True),
    ]


def test_nested_objects_are_read_four_levels_deep_and_left_open_below():
    deep = {"l2": {"l3": {"l4": {"l5": {"x": 1}}}}}
    reading = contract_from_example(json.dumps(deep))
    l4 = reading.contract["properties"]["l2"]["properties"]["l3"]["properties"]["l4"]
    assert l4["properties"]["l5"] == {"type": "object"}


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("{", "syntax"),
        ("[1]", "not_object"),
        ("{}", "no_fields"),
        ('{"n": 12345678901234567890}', "inexact_number"),
        (" " * (EXAMPLE_MAX_CHARACTERS + 1), "too_large"),
        (json.dumps({f"f{n}": 1 for n in range(501)}), "too_large"),
    ],
)
def test_text_that_gives_no_contract_is_refused_with_the_reason(text, problem):
    with pytest.raises(ExampleProblemError) as raised:
        contract_from_example(text)
    assert raised.value.problem == problem
