"""Tests for intric.flows.output_processing — pure function module."""

from __future__ import annotations

import pytest

from intric.flows.output_processing import (
    compile_validators,
    parse_json_output,
    prune_extras_to_strict_schema,
    validate_against_contract,
    validate_schema_syntax,
)
from intric.main.exceptions import TypedIOValidationException

# --- parse_json_output ---


def test_parse_json_output_valid_object():
    result = parse_json_output('{"key": "val"}')
    assert result == {"key": "val"}


def test_parse_json_output_valid_array():
    result = parse_json_output("[1, 2, 3]")
    assert result == [1, 2, 3]


def test_parse_json_output_accepts_fenced_json_object():
    result = parse_json_output('```json\n{"key": "val"}\n```')
    assert result == {"key": "val"}


def test_parse_json_output_accepts_wrapped_json_object():
    result = parse_json_output('Here is the result:\n{"key": "val"}\nTack!')
    assert result == {"key": "val"}


def test_parse_json_output_empty_response_has_clearer_message():
    with pytest.raises(TypedIOValidationException, match="response was empty"):
        parse_json_output("   \n\t  ")


def test_parse_json_output_invalid_json():
    with pytest.raises(TypedIOValidationException, match="not valid JSON"):
        parse_json_output("not json at all")


def test_parse_json_output_scalar_rejected():
    with pytest.raises(
        TypedIOValidationException, match="Expected JSON object or array"
    ):
        parse_json_output('"just a string"')


def test_parse_json_output_number_rejected():
    with pytest.raises(
        TypedIOValidationException, match="Expected JSON object or array"
    ):
        parse_json_output("42")


def test_parse_json_output_error_code():
    with pytest.raises(TypedIOValidationException) as exc_info:
        parse_json_output("not json")
    assert exc_info.value.code == "typed_io_output_parse_failed"


# --- validate_against_contract ---


def test_validate_against_contract_passes():
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    validate_against_contract({"name": "Alice"}, schema, label="test")


def test_validate_against_contract_fails():
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    with pytest.raises(TypedIOValidationException, match="test"):
        validate_against_contract({}, schema, label="test")


def test_validate_against_contract_error_code():
    schema = {"type": "object", "required": ["x"]}
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract({}, schema, label="output")
    assert exc_info.value.code == "typed_io_contract_violation"


def test_prune_extras_to_strict_schema_drops_extra_item_property():
    schema = {
        "type": "object",
        "required": ["beslutslista"],
        "properties": {
            "beslutslista": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["rubrik", "beslut", "omrostning"],
                    "properties": {
                        "rubrik": {"type": "string"},
                        "beslut": {"type": "string"},
                        "omrostning": {"type": "boolean"},
                        "roster_for": {"type": "string"},
                        "roster_emot": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            }
        },
        "additionalProperties": False,
    }
    data = {
        "beslutslista": [
            {
                "rubrik": "Budget",
                "beslut": "Godkänd",
                "omrostning": False,
                "rubrik_kommentar": "extra",
            }
        ]
    }

    result = prune_extras_to_strict_schema(data, schema)

    assert result.dropped_paths == ("/beslutslista/0/rubrik_kommentar",)
    assert "rubrik_kommentar" not in data["beslutslista"][0]
    validate_against_contract(data, schema, label="Step 4 output")


def test_prune_extras_to_strict_schema_leaves_permissive_schemas_unchanged():
    schema = {
        "type": "object",
        "properties": {"rubrik": {"type": "string"}},
    }
    data = {"rubrik": "Budget", "rubrik_kommentar": "kept"}

    result = prune_extras_to_strict_schema(data, schema)

    assert result.dropped_paths == ()
    assert data["rubrik_kommentar"] == "kept"


def test_prune_extras_to_strict_schema_is_deep_and_idempotent():
    schema = {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"title": {"type": "string"}},
                                "additionalProperties": False,
                            },
                        }
                    },
                    "additionalProperties": False,
                },
            }
        },
        "additionalProperties": False,
    }
    data = {
        "sections": [
            {
                "items": [
                    {"title": "One", "unexpected": "drop"},
                ],
                "section_extra": "drop",
            }
        ],
    }

    first = prune_extras_to_strict_schema(data, schema)
    second = prune_extras_to_strict_schema(data, schema)

    assert first.dropped_paths == (
        "/sections/0/section_extra",
        "/sections/0/items/0/unexpected",
    )
    assert second.dropped_paths == ()
    assert data == {"sections": [{"items": [{"title": "One"}]}]}


def test_prune_extras_to_strict_schema_skips_composition_nodes():
    schema = {
        "oneOf": [
            {
                "type": "object",
                "properties": {"title": {"type": "string"}},
                "additionalProperties": False,
            }
        ]
    }
    data = {"title": "One", "unexpected": "kept"}

    result = prune_extras_to_strict_schema(data, schema)

    assert result.dropped_paths == ()
    assert data["unexpected"] == "kept"


def test_pruned_output_still_fails_missing_required():
    schema = {
        "type": "object",
        "required": ["rubrik"],
        "properties": {"rubrik": {"type": "string"}},
        "additionalProperties": False,
    }
    data = {"rubrik_kommentar": "drop"}

    result = prune_extras_to_strict_schema(data, schema)

    assert result.dropped_paths == ("/rubrik_kommentar",)
    with pytest.raises(TypedIOValidationException, match="'rubrik' is a required"):
        validate_against_contract(data, schema, label="Step output")


def test_pruned_output_still_fails_wrong_type():
    schema = {
        "type": "object",
        "required": ["omrostning"],
        "properties": {"omrostning": {"type": "boolean"}},
        "additionalProperties": False,
    }
    data = {"omrostning": "nej", "extra": "drop"}

    result = prune_extras_to_strict_schema(data, schema)

    assert result.dropped_paths == ("/extra",)
    with pytest.raises(TypedIOValidationException, match="is not of type"):
        validate_against_contract(data, schema, label="Step output")


# --- validate_schema_syntax ---


def test_validate_schema_syntax_valid():
    validate_schema_syntax({"type": "object"}, label="test")


def test_validate_schema_syntax_invalid():
    with pytest.raises(TypedIOValidationException, match="not a valid JSON Schema"):
        validate_schema_syntax({"type": "not_a_type"}, label="test")


def test_validate_schema_syntax_error_code():
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_schema_syntax({"type": "not_a_type"}, label="test")
    assert exc_info.value.code == "typed_io_invalid_schema"


# --- compile_validators ---


class _FakeStep:
    def __init__(self, step_order, input_contract=None, output_contract=None):
        self.step_order = step_order
        self.input_contract = input_contract
        self.output_contract = output_contract


def test_compile_validators_reusable():
    steps = [
        _FakeStep(
            1, input_contract={"type": "object"}, output_contract={"type": "array"}
        ),
        _FakeStep(2, output_contract={"type": "string"}),
    ]
    compiled = compile_validators(steps)
    assert ("input", 1) in compiled
    assert ("output", 1) in compiled
    assert ("input", 2) not in compiled
    assert ("output", 2) in compiled
    # Verify they're actual validators
    compiled[("input", 1)].validate({})
    compiled[("output", 1)].validate([])


def test_compile_validators_empty_steps():
    assert compile_validators([]) == {}


def test_compile_validators_no_contracts():
    steps = [_FakeStep(1)]
    assert compile_validators(steps) == {}


def test_compile_validators_keeps_explicit_empty_contracts():
    steps = [_FakeStep(1, input_contract={}, output_contract={})]

    compiled = compile_validators(steps)

    assert ("input", 1) in compiled
    assert ("output", 1) in compiled
    compiled[("input", 1)].validate({"anything": True})
    compiled[("output", 1)].validate(["anything"])
