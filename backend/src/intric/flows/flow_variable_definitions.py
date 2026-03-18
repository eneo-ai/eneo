from __future__ import annotations

from enum import Enum


class VariableShape(str, Enum):
    SCALAR = "scalar"
    MAPPING = "mapping"
    SEQUENCE = "sequence"


RESERVED_RUNTIME_VARIABLES: frozenset[str] = frozenset({
    "datum",
    "flow",
    "flow_input",
    "step_input",
    "transkribering",
    "föregående_steg",
    "indata_text",
    "indata_json",
    "indata_filer",
})

RESERVED_RUNTIME_VARIABLES_NORMALIZED: frozenset[str] = frozenset(
    variable.casefold() for variable in RESERVED_RUNTIME_VARIABLES
)

RUNTIME_VARIABLE_SHAPES: dict[str, VariableShape] = {
    "datum": VariableShape.SCALAR,
    "flow": VariableShape.MAPPING,
    "flow_input": VariableShape.MAPPING,
    "transkribering": VariableShape.SCALAR,
    "föregående_steg": VariableShape.SCALAR,
    "indata_text": VariableShape.SCALAR,
    "indata_json": VariableShape.MAPPING,
    "indata_filer": VariableShape.SEQUENCE,
}

STEP_INPUT_KEY_SHAPES: dict[str, VariableShape] = {
    "text": VariableShape.SCALAR,
    "file_ids": VariableShape.SEQUENCE,
    "extracted_text_length": VariableShape.SCALAR,
    "input_format": VariableShape.SCALAR,
}


def runtime_variable_shape(root: str) -> VariableShape | None:
    if root == "step_input":
        return VariableShape.MAPPING
    return RUNTIME_VARIABLE_SHAPES.get(root)


def step_input_key_shape(key: str) -> VariableShape | None:
    return STEP_INPUT_KEY_SHAPES.get(key)
