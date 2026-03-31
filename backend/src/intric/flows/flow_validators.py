from __future__ import annotations

from enum import Enum
import json
import re
from typing import Any, cast

from intric.database.tables.flow_tables import (
    FLOW_STEP_INPUT_SOURCE_VALUES,
    FLOW_STEP_INPUT_TYPE_VALUES,
    FLOW_STEP_MCP_POLICY_VALUES,
    FLOW_STEP_OUTPUT_MODE_VALUES,
    FLOW_STEP_OUTPUT_TYPE_VALUES,
)
from intric.flows.domain.flow import FlowStep, JsonObject
from intric.flows.flow_validators_form import (
    normalize_legacy_form_schema,
    validate_form_schema,
    validate_variable_alias_collisions,
)
from intric.flows.flow_validators_http import (
    validate_http_input_config,
    validate_http_output_config,
)
from intric.flows.flow_validators_template import (
    validate_template_fill_output_config,
)
from intric.flows.output_modes import transcribe_only_violation
from intric.flows.output_processing import validate_schema_syntax
from intric.flows.runtime_input import build_runtime_input_config
from intric.flows.step_chain_rules import find_first_step_chain_violation
from intric.flows.template_reference_analyzer import analyze_template, consumes_runtime_input
from intric.flows.transcription_config import (
    FlowTranscriptionConfigError,
    parse_transcription_config,
)
from intric.flows.type_policies import INPUT_TYPE_POLICIES
from intric.flows.variable_resolver import iter_template_expressions
from intric.main.exceptions import BadRequestException, TypedIOValidationException

_STEP_REFERENCE_PATTERN = re.compile(r"^step_(\d+)$")
_ALLOWED_FLOW_INPUT_SOURCES = set(FLOW_STEP_INPUT_SOURCE_VALUES)
_ALLOWED_FLOW_INPUT_TYPES = set(FLOW_STEP_INPUT_TYPE_VALUES)
_ALLOWED_FLOW_OUTPUT_MODES = set(FLOW_STEP_OUTPUT_MODE_VALUES)
_ALLOWED_FLOW_OUTPUT_TYPES = set(FLOW_STEP_OUTPUT_TYPE_VALUES)
_ALLOWED_FLOW_MCP_POLICIES = set(FLOW_STEP_MCP_POLICY_VALUES)
__all__ = [
    "normalize_legacy_form_schema",
    "validate_form_schema",
    "validate_steps",
    "validate_variable_alias_collisions",
]


def validate_steps(
    steps: list[FlowStep],
    *,
    metadata_json: JsonObject | None = None,
    require_complete_template_fill_config: bool = False,
) -> None:
    if not steps:
        return

    sorted_steps = sorted(steps, key=lambda item: item.step_order)
    step_orders = [step.step_order for step in sorted_steps]
    if len(step_orders) != len(set(step_orders)):
        raise BadRequestException("Duplicate step_order detected.")

    expected_orders = list(range(1, len(sorted_steps) + 1))
    if step_orders != expected_orders:
        raise BadRequestException("Step order must be contiguous and start at 1.")

    normalized_names: set[str] = set()
    for step in sorted_steps:
        if step.user_description is None:
            continue
        normalized_name = step.user_description.strip().casefold()
        if not normalized_name:
            continue
        if normalized_name in normalized_names:
            raise BadRequestException(
                "Step names must be unique (case-insensitive) for publishable flows."
            )
        normalized_names.add(normalized_name)

    chain_violation = find_first_step_chain_violation(sorted_steps)
    if chain_violation is not None:
        raise BadRequestException(chain_violation.message)

    seen: set[int] = set()
    for step in sorted_steps:
        seen.add(step.step_order)
        _validate_step_enum_values(step)
        if step.input_source in ("http_get", "http_post"):
            validate_http_input_config(step=step)
        if step.output_mode == "http_post":
            validate_http_output_config(step=step)
        transcribe_only_error = transcribe_only_violation(
            step_order=step.step_order,
            input_type=step.input_type,
            output_type=step.output_type,
            output_mode=step.output_mode,
        )
        if transcribe_only_error is not None:
            raise BadRequestException(transcribe_only_error)
        if step.output_mode == "template_fill":
            validate_template_fill_output_config(
                step=step,
                available_orders=seen,
                require_complete_config=require_complete_template_fill_config,
            )
        input_policy = INPUT_TYPE_POLICIES.get(step.input_type)
        if input_policy and not input_policy.supported:
            raise BadRequestException(
                f"Step {step.step_order}: {_enum_value(step.input_type)} is not yet supported."
            )
        if step.input_contract and input_policy and not input_policy.contract_allowed:
            raise BadRequestException(
                f"Step {step.step_order}: input_contract is not supported for "
                f"input_type '{_enum_value(step.input_type)}'."
            )
        if step.input_contract:
            try:
                validate_schema_syntax(
                    step.input_contract,
                    label=f"Step {step.step_order} input_contract",
                )
            except TypedIOValidationException as exc:
                raise BadRequestException(str(exc)) from exc
        if step.output_contract:
            try:
                validate_schema_syntax(
                    step.output_contract,
                    label=f"Step {step.step_order} output_contract",
                )
            except TypedIOValidationException as exc:
                raise BadRequestException(str(exc)) from exc
            _validate_output_contract_compatibility(step=step)

        if step.input_bindings is not None:
            _validate_binding_references(
                input_bindings=step.input_bindings,
                current_step_order=step.step_order,
                available_orders=seen,
            )
        _validate_runtime_input_publish_rules(step=step)

    _validate_audio_transcription_settings(
        steps=sorted_steps,
        metadata_json=metadata_json,
    )


def _validate_step_enum_values(step: FlowStep) -> None:
    if step.input_source not in _ALLOWED_FLOW_INPUT_SOURCES:
        raise BadRequestException(
            f"Step {step.step_order}: unsupported input_source '{_enum_value(step.input_source)}'."
        )
    if step.input_type not in _ALLOWED_FLOW_INPUT_TYPES:
        raise BadRequestException(
            f"Step {step.step_order}: unsupported input_type '{_enum_value(step.input_type)}'."
        )
    if step.output_mode not in _ALLOWED_FLOW_OUTPUT_MODES:
        raise BadRequestException(
            f"Step {step.step_order}: unsupported output_mode '{_enum_value(step.output_mode)}'."
        )
    if step.output_type not in _ALLOWED_FLOW_OUTPUT_TYPES:
        raise BadRequestException(
            f"Step {step.step_order}: unsupported output_type '{_enum_value(step.output_type)}'."
        )
    if step.mcp_policy not in _ALLOWED_FLOW_MCP_POLICIES:
        raise BadRequestException(
            f"Step {step.step_order}: unsupported mcp_policy '{_enum_value(step.mcp_policy)}'."
        )


def _validate_output_contract_compatibility(*, step: FlowStep) -> None:
    if step.output_contract is None:
        return
    if step.output_mode == "template_fill":
        raise BadRequestException(
            f"Step {step.step_order}: output_contract is not supported for output_mode 'template_fill'."
        )
    if step.output_type == "text":
        raise BadRequestException(
            f"Step {step.step_order}: output_contract is not supported for output_type 'text'."
        )
    if step.output_type in {"pdf", "docx"}:
        schema_type = _schema_type_hint(step.output_contract)
        if schema_type not in {"object", "array"}:
            raise BadRequestException(
                f"Step {step.step_order}: output_contract for output_type '{step.output_type}' "
                "must declare schema type 'object' or 'array'."
            )


def _schema_type_hint(schema: dict[str, Any]) -> str:
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        return raw_type
    if isinstance(raw_type, list):
        declared = [item for item in raw_type if isinstance(item, str)]
        if "object" in declared:
            return "object"
        if "array" in declared:
            return "array"
    if isinstance(schema.get("properties"), dict):
        return "object"
    if "items" in schema:
        return "array"
    return "unknown"


def _enum_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    return value


def _validate_audio_transcription_settings(
    *,
    steps: list[FlowStep],
    metadata_json: JsonObject | None,
) -> None:
    if not any(step.input_type == "audio" for step in steps):
        return

    try:
        config = parse_transcription_config(cast(dict[str, Any] | None, metadata_json))
    except FlowTranscriptionConfigError as exc:
        raise BadRequestException(str(exc)) from exc

    if not config.enabled:
        raise BadRequestException(
            "Transcription must be enabled when using audio input steps."
        )
    if config.model_id is None:
        raise BadRequestException(
            "A transcription model must be selected when using audio input steps."
        )


def _validate_binding_references(
    *,
    input_bindings: JsonObject,
    current_step_order: int,
    available_orders: set[int],
) -> None:
    binding_payload = json.dumps(input_bindings)
    for expression in iter_template_expressions(binding_payload):
        if not expression.startswith("step_"):
            continue

        head = expression.split(".", maxsplit=1)[0]
        step_ref = _STEP_REFERENCE_PATTERN.match(head)
        if step_ref is None:
            raise BadRequestException(
                f"Invalid step reference '{head}' in input bindings."
            )

        referenced_order = int(step_ref.group(1))
        if referenced_order >= current_step_order:
            raise BadRequestException(
                "Input bindings may only reference outputs from earlier steps."
            )
        if referenced_order not in available_orders:
            raise BadRequestException(
                f"Input binding references unknown step order: {referenced_order}."
            )


def _validate_runtime_input_publish_rules(*, step: FlowStep) -> None:
    runtime_input = build_runtime_input_config(step.input_config)
    if not runtime_input.enabled:
        return

    if step.output_mode == "transcribe_only" and runtime_input.input_format != "audio":
        raise BadRequestException(
            f"Step {step.step_order}: transcribe_only steps require runtime_input.input_format 'audio'."
        )

    bindings = step.input_bindings if isinstance(step.input_bindings, dict) else None
    if bindings is None:
        return

    question_binding = bindings.get("question")
    if isinstance(question_binding, str) and question_binding.strip():
        references = analyze_template(
            question_binding,
            step_refs={},
            form_field_names=set(),
        )
        if not consumes_runtime_input(references):
            raise BadRequestException(
                f"Step {step.step_order}: explicit question bindings must reference step_input.* when runtime input is enabled."
            )
