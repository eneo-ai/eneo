from __future__ import annotations

from intric.flows.flow_variable_definitions import (
    RESERVED_RUNTIME_VARIABLES,
    RUNTIME_VARIABLE_SHAPES,
    STEP_INPUT_KEY_SHAPES,
    VariableShape,
)


def test_runtime_variables_include_datum() -> None:
    assert "datum" in RESERVED_RUNTIME_VARIABLES
    assert RUNTIME_VARIABLE_SHAPES["datum"] is VariableShape.SCALAR


def test_runtime_variable_shapes_model_sequence_inputs() -> None:
    assert RUNTIME_VARIABLE_SHAPES["indata_filer"] is VariableShape.SEQUENCE


def test_step_input_key_shapes_are_explicit() -> None:
    assert STEP_INPUT_KEY_SHAPES["text"] is VariableShape.SCALAR
    assert STEP_INPUT_KEY_SHAPES["file_ids"] is VariableShape.SEQUENCE
    assert STEP_INPUT_KEY_SHAPES["input_format"] is VariableShape.SCALAR
