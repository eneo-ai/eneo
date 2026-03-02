"""Tests for intric.flows.output_processing — pure function module."""
from __future__ import annotations

import pytest

from intric.flows.output_processing import (
    compile_validators,
    parse_json_output,
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


def test_parse_json_output_invalid_json():
    with pytest.raises(TypedIOValidationException, match="not valid JSON"):
        parse_json_output("not json at all")


def test_parse_json_output_scalar_rejected():
    with pytest.raises(TypedIOValidationException, match="Expected JSON object or array"):
        parse_json_output('"just a string"')


def test_parse_json_output_number_rejected():
    with pytest.raises(TypedIOValidationException, match="Expected JSON object or array"):
        parse_json_output("42")


def test_parse_json_output_error_code():
    with pytest.raises(TypedIOValidationException) as exc_info:
        parse_json_output("not json")
    assert exc_info.value.code == "typed_io_output_parse_failed"


# --- validate_against_contract ---


def test_validate_against_contract_passes():
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    validate_against_contract({"name": "Alice"}, schema, label="test")


def test_validate_against_contract_fails():
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    with pytest.raises(TypedIOValidationException, match="test"):
        validate_against_contract({}, schema, label="test")


def test_validate_against_contract_error_code():
    schema = {"type": "object", "required": ["x"]}
    with pytest.raises(TypedIOValidationException) as exc_info:
        validate_against_contract({}, schema, label="output")
    assert exc_info.value.code == "typed_io_contract_violation"


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
        _FakeStep(1, input_contract={"type": "object"}, output_contract={"type": "array"}),
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
