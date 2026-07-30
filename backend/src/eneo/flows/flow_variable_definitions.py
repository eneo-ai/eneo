from __future__ import annotations

import re
from enum import Enum
from typing import TypedDict

from eneo.flows.flow_run_input_envelope import (
    FLOW_INPUT_TRANSCRIPTION_KEY,
    FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS,
)


class FlowVariableDefinitionManifest(TypedDict):
    reservedRuntimeVariables: list[str]
    formFieldNamespaceHeads: list[str]
    primaryFlowInputKeys: list[str]
    reservedFormFieldInputKeys: list[str]


class VariableShape(str, Enum):
    SCALAR = "scalar"
    MAPPING = "mapping"
    SEQUENCE = "sequence"


FLOW_INPUT_TEXT_ALIAS = "indata_text"
FLOW_INPUT_JSON_ALIAS = "indata_json"
PREVIOUS_STEP_TEXT_ALIAS = "föregående_steg"


RESERVED_RUNTIME_VARIABLES: frozenset[str] = frozenset(
    {
        "datum",
        "flow",
        "flow_input",
        "step_input",
        FLOW_INPUT_TRANSCRIPTION_KEY,
        PREVIOUS_STEP_TEXT_ALIAS,
        FLOW_INPUT_TEXT_ALIAS,
        FLOW_INPUT_JSON_ALIAS,
    }
)

RESERVED_RUNTIME_VARIABLES_NORMALIZED: frozenset[str] = frozenset(
    variable.casefold() for variable in RESERVED_RUNTIME_VARIABLES
)
FORM_FIELD_NAMESPACE_HEADS: frozenset[str] = frozenset(
    {
        "flow",
        "flow_input",
        "step_input",
    }
)
FORM_FIELD_NAMESPACE_HEADS_NORMALIZED: frozenset[str] = frozenset(
    name.casefold() for name in FORM_FIELD_NAMESPACE_HEADS
)
PRIMARY_FLOW_INPUT_KEYS: frozenset[str] = frozenset(
    {
        "file_ids",
        "json",
        "structured",
        "text",
        "transcribed_text",
        "transcription",
        "transcript",
        FLOW_INPUT_TRANSCRIPTION_KEY,
    }
)
RESERVED_FORM_FIELD_INPUT_KEYS: frozenset[str] = (
    PRIMARY_FLOW_INPUT_KEYS | FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS
)
RESERVED_FORM_FIELD_INPUT_KEYS_NORMALIZED: frozenset[str] = frozenset(
    name.casefold() for name in RESERVED_FORM_FIELD_INPUT_KEYS
)
STEP_ALIAS_VARIABLE_PATTERN = re.compile(r"^step_\d+($|[._])")

RUNTIME_VARIABLE_SHAPES: dict[str, VariableShape] = {
    "datum": VariableShape.SCALAR,
    "flow": VariableShape.MAPPING,
    "flow_input": VariableShape.MAPPING,
    FLOW_INPUT_TRANSCRIPTION_KEY: VariableShape.SCALAR,
    PREVIOUS_STEP_TEXT_ALIAS: VariableShape.SCALAR,
    FLOW_INPUT_TEXT_ALIAS: VariableShape.SCALAR,
    FLOW_INPUT_JSON_ALIAS: VariableShape.MAPPING,
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


def is_reserved_runtime_variable(name: str) -> bool:
    return name.strip().casefold() in RESERVED_RUNTIME_VARIABLES_NORMALIZED


def is_step_alias_variable(name: str) -> bool:
    return STEP_ALIAS_VARIABLE_PATTERN.match(name.strip().casefold()) is not None


def is_form_field_namespace_head(name: str) -> bool:
    return name.strip().casefold() in FORM_FIELD_NAMESPACE_HEADS_NORMALIZED


def is_reserved_form_field_input_key(name: str) -> bool:
    return name.strip().casefold() in RESERVED_FORM_FIELD_INPUT_KEYS_NORMALIZED


def can_expose_form_field_bare_alias(name: str) -> bool:
    field_name = name.strip()
    if not field_name:
        return False
    if "." in field_name:
        return False
    if is_form_field_namespace_head(field_name):
        return False
    if is_reserved_form_field_input_key(field_name):
        return False
    if is_reserved_runtime_variable(field_name):
        return False
    if is_step_alias_variable(field_name):
        return False
    return True


def form_field_reference_expression(field_name: str) -> str:
    return f"{{{{ flow_input.{field_name.strip()} }}}}"


def template_placeholder_form_field_name(placeholder: str) -> str | None:
    """Return the Flow input field declared by a safe template placeholder."""

    candidate = " ".join(placeholder.strip().split())
    if not candidate:
        return None

    normalized = candidate.casefold()
    for prefix in ("flow_input.", "flow.input."):
        if normalized.startswith(prefix):
            candidate = candidate[len(prefix) :].strip()
            break
    return candidate if can_expose_form_field_bare_alias(candidate) else None


def flow_variable_definition_manifest() -> FlowVariableDefinitionManifest:
    return {
        "reservedRuntimeVariables": sorted(RESERVED_RUNTIME_VARIABLES),
        "formFieldNamespaceHeads": sorted(FORM_FIELD_NAMESPACE_HEADS),
        "primaryFlowInputKeys": sorted(PRIMARY_FLOW_INPUT_KEYS),
        "reservedFormFieldInputKeys": sorted(RESERVED_FORM_FIELD_INPUT_KEYS),
    }
