from __future__ import annotations

from intric.flows.flow_run_input_envelope import FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS
from intric.flows.flow_variable_definitions import (
    RESERVED_FORM_FIELD_INPUT_KEYS,
    RESERVED_RUNTIME_VARIABLES,
    RUNTIME_VARIABLE_SHAPES,
    STEP_INPUT_KEY_SHAPES,
    VariableShape,
    is_reserved_form_field_input_key,
)


def test_runtime_variables_include_datum() -> None:
    assert "datum" in RESERVED_RUNTIME_VARIABLES
    assert RUNTIME_VARIABLE_SHAPES["datum"] is VariableShape.SCALAR


def test_step_input_key_shapes_are_explicit() -> None:
    assert STEP_INPUT_KEY_SHAPES["text"] is VariableShape.SCALAR
    assert STEP_INPUT_KEY_SHAPES["file_ids"] is VariableShape.SEQUENCE
    assert STEP_INPUT_KEY_SHAPES["input_format"] is VariableShape.SCALAR


def test_reserved_form_field_input_keys_include_run_envelope_keys() -> None:
    assert FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS <= RESERVED_FORM_FIELD_INPUT_KEYS
    assert is_reserved_form_field_input_key("expected_flow_version") is True
    assert is_reserved_form_field_input_key("step_inputs") is True
    assert is_reserved_form_field_input_key("case_id") is False
