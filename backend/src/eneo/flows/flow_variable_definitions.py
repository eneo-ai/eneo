from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypedDict

from pydantic import ValidationError

from eneo.flows.domain.text_processing import TextProcessingMode, text_processing_config
from eneo.flows.flow_run_input_envelope import (
    FLOW_INPUT_TRANSCRIPTION_KEY,
    FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS,
)


class FlowVariableDefinitionManifest(TypedDict):
    reservedRuntimeVariables: list[str]
    sectionRuntimeVariables: list[str]
    stepInputKeyShapes: dict[str, str]
    flowInputAliases: list[str]
    previousStepAlias: str
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

# The run-payload keys each run-input alias is read from; the first key that
# holds a value defines it. A run defines the alias only from a payload that
# carries the key, so which flows can receive it is decided below.
FLOW_INPUT_ALIAS_PAYLOAD_KEYS: dict[str, tuple[str, ...]] = {
    FLOW_INPUT_TEXT_ALIAS: ("text",),
    FLOW_INPUT_JSON_ALIAS: ("json", "structured"),
}
FLOW_INPUT_ALIASES: frozenset[str] = frozenset(FLOW_INPUT_ALIAS_PAYLOAD_KEYS)


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
FLOW_INPUT_KEY_SHAPES: dict[str, VariableShape] = {
    "file_ids": VariableShape.SEQUENCE,
    "json": VariableShape.MAPPING,
    "structured": VariableShape.MAPPING,
    "text": VariableShape.SCALAR,
    "transcribed_text": VariableShape.SCALAR,
    "transcription": VariableShape.SCALAR,
    "transcript": VariableShape.SCALAR,
    FLOW_INPUT_TRANSCRIPTION_KEY: VariableShape.SCALAR,
}
PRIMARY_FLOW_INPUT_KEYS: frozenset[str] = frozenset(FLOW_INPUT_KEY_SHAPES)
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

SECTION_VARIABLE_SHAPES: dict[str, VariableShape] = {
    "section_index": VariableShape.SCALAR,
}


@dataclass(frozen=True, slots=True)
class FlowRunInput:
    """What the run form of a flow collects: the run contract's form fields and
    the steps that take uploaded files.

    The run dialog offers a free text box only when it collects neither, and
    the documented run contract lists only the declared form fields and
    uploads. A step that reads the run-input aliases on a flow that collects
    fields or files is refused at publish (the frontend's
    ``showFreeformTextInput`` is the same rule). This says what the run form
    declares, not what a runtime payload can hold.
    """

    form_fields: bool = False
    runtime_files: bool = False

    @property
    def free_text(self) -> bool:
        return not (self.form_fields or self.runtime_files)


def unreceived_flow_input_aliases(run_input: FlowRunInput) -> frozenset[str]:
    """The run-input aliases this flow's run form does not declare."""

    return frozenset() if run_input.free_text else FLOW_INPUT_ALIASES


def variable_path_segments(path: str) -> list[str]:
    """The segments the resolver walks a template path by: split at each dot,
    each stripped (an empty one is the resolver's error to report)."""

    return [segment.strip() for segment in path.split(".")]


def reads_unreceived_run_input(expression: str, run_input: FlowRunInput) -> bool:
    """Whether a template expression reads free-text run input this flow's run
    form does not declare: a run-input alias (``indata_text``) or the payload key
    behind one (``flow_input.text``, ``flow.input.json``)."""

    unreceived = unreceived_flow_input_aliases(run_input)
    if not unreceived:
        return False
    head, *path = variable_path_segments(expression)
    if head in unreceived:
        return True
    if head == "flow" and path[:1] == ["input"]:
        path = path[1:]
    elif head != "flow_input":
        return False
    unreceived_keys = {
        key for alias in unreceived for key in FLOW_INPUT_ALIAS_PAYLOAD_KEYS[alias]
    }
    return bool(path) and path[0] in unreceived_keys


def flow_input_alias_source(
    alias: str, payload: Mapping[str, Any]
) -> tuple[str, Any] | None:
    """The payload key and value a run defines ``alias`` from; None when it
    defines none (the key is absent, a blank text, or a value of the wrong shape)."""

    shape = RUNTIME_VARIABLE_SHAPES[alias]
    for key in FLOW_INPUT_ALIAS_PAYLOAD_KEYS[alias]:
        value = payload.get(key)
        if value is None:
            continue
        if shape is VariableShape.SCALAR:
            usable = isinstance(value, str) and bool(value.strip())
        else:
            usable = isinstance(value, (dict, list))
        return (key, value) if usable else None
    return None


def runtime_variables_for_step(
    input_config: dict[str, Any] | None = None,
) -> frozenset[str]:
    try:
        processing = text_processing_config(input_config)
    except ValidationError:
        return RESERVED_RUNTIME_VARIABLES
    if (
        processing is not None
        and processing.mode == TextProcessingMode.PROCESS_EACH_SECTION
    ):
        return RESERVED_RUNTIME_VARIABLES | frozenset(SECTION_VARIABLE_SHAPES)
    return RESERVED_RUNTIME_VARIABLES


def runtime_variable_shape(root: str) -> VariableShape | None:
    if root == "step_input":
        return VariableShape.MAPPING
    return RUNTIME_VARIABLE_SHAPES.get(root) or SECTION_VARIABLE_SHAPES.get(root)


def step_input_key_shape(key: str) -> VariableShape | None:
    return STEP_INPUT_KEY_SHAPES.get(key)


def flow_input_key_shape(key: str) -> VariableShape | None:
    return FLOW_INPUT_KEY_SHAPES.get(key)


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


def flow_variable_definition_manifest(
    input_config: dict[str, Any] | None = None,
) -> FlowVariableDefinitionManifest:
    return {
        "reservedRuntimeVariables": sorted(runtime_variables_for_step(input_config)),
        "sectionRuntimeVariables": sorted(SECTION_VARIABLE_SHAPES),
        "stepInputKeyShapes": {
            key: shape.value for key, shape in sorted(STEP_INPUT_KEY_SHAPES.items())
        },
        "flowInputAliases": sorted(FLOW_INPUT_ALIASES | {FLOW_INPUT_TRANSCRIPTION_KEY}),
        "previousStepAlias": PREVIOUS_STEP_TEXT_ALIAS,
        "formFieldNamespaceHeads": sorted(FORM_FIELD_NAMESPACE_HEADS),
        "primaryFlowInputKeys": sorted(PRIMARY_FLOW_INPUT_KEYS),
        "reservedFormFieldInputKeys": sorted(RESERVED_FORM_FIELD_INPUT_KEYS),
    }
