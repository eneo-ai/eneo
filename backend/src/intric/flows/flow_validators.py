from __future__ import annotations

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
from intric.flows.flow import FlowStep, JsonObject
from intric.flows.output_modes import transcribe_only_violation
from intric.flows.output_processing import validate_schema_syntax
from intric.flows.step_chain_rules import find_first_step_chain_violation
from intric.flows.transcription_config import (
    FlowTranscriptionConfigError,
    parse_transcription_config,
)
from intric.flows.type_policies import INPUT_TYPE_POLICIES
from intric.flows.variable_resolver import iter_template_expressions
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException, TypedIOValidationException

_STEP_REFERENCE_PATTERN = re.compile(r"^step_(\d+)$")

_ALLOWED_FORM_FIELD_TYPES = {"text", "multiselect", "number", "date", "select"}
_LEGACY_FORM_FIELD_TYPE_NORMALIZATION = {
    "string": "text",
    "email": "text",
    "textarea": "text",
}
_RESERVED_VARIABLE_ALIASES = {
    "flow",
    "flow_input",
    "transkribering",
    "föregående_steg",
    "indata_text",
    "indata_json",
    "indata_filer",
}
_RESERVED_VARIABLE_ALIASES_NORMALIZED = {
    alias.casefold() for alias in _RESERVED_VARIABLE_ALIASES
}
_STEP_ALIAS_PATTERN = re.compile(r"^step_\d+($|[._])")
_ALLOWED_FLOW_INPUT_SOURCES = set(FLOW_STEP_INPUT_SOURCE_VALUES)
_ALLOWED_FLOW_INPUT_TYPES = set(FLOW_STEP_INPUT_TYPE_VALUES)
_ALLOWED_FLOW_OUTPUT_MODES = set(FLOW_STEP_OUTPUT_MODE_VALUES)
_ALLOWED_FLOW_OUTPUT_TYPES = set(FLOW_STEP_OUTPUT_TYPE_VALUES)
_ALLOWED_FLOW_MCP_POLICIES = set(FLOW_STEP_MCP_POLICY_VALUES)


def validate_steps(
    steps: list[FlowStep],
    *,
    metadata_json: JsonObject | None = None,
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
            _validate_http_input_config(step=step)
        if step.output_mode == "http_post":
            _validate_http_output_config(step=step)
        transcribe_only_error = transcribe_only_violation(
            step_order=step.step_order,
            input_type=step.input_type,
            output_type=step.output_type,
            output_mode=step.output_mode,
        )
        if transcribe_only_error is not None:
            raise BadRequestException(transcribe_only_error)
        input_policy = INPUT_TYPE_POLICIES.get(step.input_type)
        if input_policy and not input_policy.supported:
            raise BadRequestException(
                f"Step {step.step_order}: {step.input_type} is not yet supported."
            )
        if step.input_contract and input_policy and not input_policy.contract_allowed:
            raise BadRequestException(
                f"Step {step.step_order}: input_contract is not supported for "
                f"input_type '{step.input_type}'."
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

    _validate_audio_transcription_settings(
        steps=sorted_steps,
        metadata_json=metadata_json,
    )


def validate_form_schema(metadata_json: JsonObject | None) -> None:
    if metadata_json is None:
        return

    form_schema = metadata_json.get("form_schema")
    if form_schema is None:
        return
    if not isinstance(form_schema, dict):
        raise BadRequestException("metadata_json.form_schema must be an object.")
    form_schema_dict = cast(dict[str, Any], form_schema)

    fields = form_schema_dict.get("fields")
    if not isinstance(fields, list):
        raise BadRequestException("metadata_json.form_schema.fields must be a list.")

    seen_names: set[str] = set()
    seen_orders: set[int] = set()
    for index, field in enumerate(cast(list[object], fields)):
        if not isinstance(field, dict):
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}] must be an object."
            )
        field_dict = cast(dict[str, Any], field)
        field_name = field_dict.get("name")
        if not isinstance(field_name, str) or not field_name.strip():
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].name must be a non-empty string."
            )
        normalized_name = field_name.strip().casefold()
        if normalized_name in seen_names:
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].name must be unique."
            )
        if "." in field_name:
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].name cannot contain '.'."
            )
        if "{{" in field_name or "}}" in field_name:
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].name cannot contain template delimiters."
            )
        if normalized_name in _RESERVED_VARIABLE_ALIASES_NORMALIZED:
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].name uses a reserved variable alias."
            )
        if _STEP_ALIAS_PATTERN.match(normalized_name):
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].name cannot use reserved step alias format."
            )
        seen_names.add(normalized_name)
        field_type = field_dict.get("type")
        if not isinstance(field_type, str) or not field_type.strip():
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].type must be a non-empty string."
            )
        normalized_type = field_type.strip().casefold()
        if normalized_type not in _ALLOWED_FORM_FIELD_TYPES:
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].type must be one of "
                f"{sorted(_ALLOWED_FORM_FIELD_TYPES)}."
            )
        if "required" in field_dict and not isinstance(field_dict["required"], bool):
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].required must be a boolean."
            )
        if "order" in field_dict:
            if not isinstance(field_dict["order"], int):
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].order must be an integer."
                )
            order_value = field_dict["order"]
            if order_value < 1:
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].order must be >= 1."
                )
            if order_value in seen_orders:
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].order must be unique."
                )
            seen_orders.add(order_value)
        options = field_dict.get("options")
        if normalized_type == "multiselect":
            if options is None or not isinstance(options, list):
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].options must be a list for multiselect."
                )
            normalized_options: set[str] = set()
            for option_index, option in enumerate(cast(list[object], options)):
                if not isinstance(option, str) or not option.strip():
                    raise BadRequestException(
                        f"metadata_json.form_schema.fields[{index}].options[{option_index}] "
                        "must be a non-empty string."
                    )
                option_key = option.strip().casefold()
                if option_key in normalized_options:
                    raise BadRequestException(
                        f"metadata_json.form_schema.fields[{index}].options[{option_index}] "
                        "must be unique."
                    )
                normalized_options.add(option_key)
        elif normalized_type == "select":
            if options is not None and not isinstance(options, list):
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].options must be a list for select."
                )
            if isinstance(options, list):
                normalized_options: set[str] = set()
                for option_index, option in enumerate(cast(list[object], options)):
                    if not isinstance(option, str) or not option.strip():
                        raise BadRequestException(
                            f"metadata_json.form_schema.fields[{index}].options[{option_index}] "
                            "must be a non-empty string."
                        )
                    option_key = option.strip().casefold()
                    if option_key in normalized_options:
                        raise BadRequestException(
                            f"metadata_json.form_schema.fields[{index}].options[{option_index}] "
                            "must be unique."
                        )
                    normalized_options.add(option_key)
        elif options is not None:
            raise BadRequestException(
                f"metadata_json.form_schema.fields[{index}].options is only valid for select or multiselect."
            )


def normalize_legacy_form_schema(metadata_json: JsonObject | None) -> JsonObject | None:
    if metadata_json is None:
        return None
    form_schema = metadata_json.get("form_schema")
    if not isinstance(form_schema, dict):
        return metadata_json
    fields = form_schema.get("fields")
    if not isinstance(fields, list):
        return metadata_json

    changed = False
    normalized_fields: list[object] = []
    for field in fields:
        if not isinstance(field, dict):
            normalized_fields.append(field)
            continue
        field_dict = cast(dict[str, Any], field)
        normalized_field = dict(field_dict)
        raw_type = normalized_field.get("type")
        if isinstance(raw_type, str):
            legacy_target = _LEGACY_FORM_FIELD_TYPE_NORMALIZATION.get(raw_type.strip().casefold())
            if legacy_target is not None and legacy_target != raw_type:
                normalized_field["type"] = legacy_target
                changed = True
        normalized_fields.append(normalized_field)

    if not changed:
        return metadata_json

    normalized_form_schema = dict(form_schema)
    normalized_form_schema["fields"] = normalized_fields
    normalized_metadata = dict(metadata_json)
    normalized_metadata["form_schema"] = normalized_form_schema
    return cast(JsonObject, normalized_metadata)


def validate_variable_alias_collisions(
    *,
    steps: list[FlowStep],
    metadata_json: JsonObject | None,
) -> None:
    normalized_reserved = _RESERVED_VARIABLE_ALIASES_NORMALIZED
    field_names: dict[str, str] = {}

    form_schema = metadata_json.get("form_schema") if metadata_json else None
    fields = form_schema.get("fields") if isinstance(form_schema, dict) else None
    if isinstance(fields, list):
        for index, field in enumerate(fields):
            if not isinstance(field, dict):
                continue
            raw_name = field.get("name")
            if not isinstance(raw_name, str):
                continue
            normalized = raw_name.strip().casefold()
            if not normalized:
                continue
            if normalized in normalized_reserved:
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].name is reserved."
                )
            if _STEP_ALIAS_PATTERN.match(normalized):
                raise BadRequestException(
                    f"metadata_json.form_schema.fields[{index}].name conflicts with reserved step alias namespace."
                )
            field_names[normalized] = raw_name.strip()

    for step in steps:
        raw_name = step.user_description
        if raw_name is None:
            continue
        normalized = raw_name.strip().casefold()
        if not normalized:
            continue
        if normalized in normalized_reserved:
            raise BadRequestException(
                f"Step {step.step_order} name '{raw_name}' uses a reserved variable alias."
            )
        if _STEP_ALIAS_PATTERN.match(normalized):
            raise BadRequestException(
                f"Step {step.step_order} name '{raw_name}' conflicts with reserved step alias namespace."
            )
        if normalized in field_names:
            raise BadRequestException(
                f"Step {step.step_order} name '{raw_name}' conflicts with form field name '{field_names[normalized]}'."
            )


def _validate_step_enum_values(step: FlowStep) -> None:
    if step.input_source not in _ALLOWED_FLOW_INPUT_SOURCES:
        raise BadRequestException(
            f"Step {step.step_order}: unsupported input_source '{step.input_source}'."
        )
    if step.input_type not in _ALLOWED_FLOW_INPUT_TYPES:
        raise BadRequestException(
            f"Step {step.step_order}: unsupported input_type '{step.input_type}'."
        )
    if step.output_mode not in _ALLOWED_FLOW_OUTPUT_MODES:
        raise BadRequestException(
            f"Step {step.step_order}: unsupported output_mode '{step.output_mode}'."
        )
    if step.output_type not in _ALLOWED_FLOW_OUTPUT_TYPES:
        raise BadRequestException(
            f"Step {step.step_order}: unsupported output_type '{step.output_type}'."
        )
    if step.mcp_policy not in _ALLOWED_FLOW_MCP_POLICIES:
        raise BadRequestException(
            f"Step {step.step_order}: unsupported mcp_policy '{step.mcp_policy}'."
        )


def _validate_output_contract_compatibility(*, step: FlowStep) -> None:
    if step.output_contract is None:
        return
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


def _validate_http_input_config(*, step: FlowStep) -> None:
    if step.input_type in {"document", "file", "image", "audio"}:
        raise BadRequestException(
            f"Step {step.step_order}: input_type '{step.input_type}' is not supported with input_source '{step.input_source}'."
        )
    _validate_http_config_common(
        step_order=step.step_order,
        label="input_config",
        config=step.input_config,
        method=step.input_source,
    )
    if isinstance(step.input_config, dict) and step.input_source == "http_get":
        if "body_template" in step.input_config or "body_json" in step.input_config:
            raise BadRequestException(
                f"Step {step.step_order}: input_config body fields are only allowed for input_source 'http_post'."
            )


def _validate_http_output_config(*, step: FlowStep) -> None:
    _validate_http_config_common(
        step_order=step.step_order,
        label="output_config",
        config=step.output_config,
        method="http_post",
    )


def _validate_http_config_common(
    *,
    step_order: int,
    label: str,
    config: JsonObject | None,
    method: str,
) -> None:
    if not isinstance(config, dict):
        raise BadRequestException(
            f"Step {step_order}: {label} must be an object when using HTTP {method}."
        )
    url_value = config.get("url")
    if not isinstance(url_value, str) or not url_value.strip():
        raise BadRequestException(
            f"Step {step_order}: {label}.url is required for HTTP {method}."
        )
    headers = config.get("headers")
    if headers is not None and not isinstance(headers, dict):
        raise BadRequestException(
            f"Step {step_order}: {label}.headers must be an object."
        )
    timeout_value = config.get("timeout_seconds")
    if timeout_value is not None:
        if not isinstance(timeout_value, (int, float)):
            raise BadRequestException(
                f"Step {step_order}: {label}.timeout_seconds must be a number."
            )
        if timeout_value <= 0:
            raise BadRequestException(
                f"Step {step_order}: {label}.timeout_seconds must be greater than zero."
            )
        max_timeout = float(get_settings().flow_http_max_timeout_seconds)
        if float(timeout_value) > max_timeout:
            raise BadRequestException(
                f"Step {step_order}: {label}.timeout_seconds cannot exceed {max_timeout:g}."
            )
    response_format = config.get("response_format")
    if response_format is not None and str(response_format) not in {"text", "json"}:
        raise BadRequestException(
            f"Step {step_order}: {label}.response_format must be 'text' or 'json'."
        )
    body_template = config.get("body_template")
    if body_template is not None and not isinstance(body_template, str):
        raise BadRequestException(
            f"Step {step_order}: {label}.body_template must be a string."
        )
    body_json = config.get("body_json")
    if body_json is not None and not isinstance(body_json, (dict, list)):
        raise BadRequestException(
            f"Step {step_order}: {label}.body_json must be an object or array."
        )
    if body_template is not None and body_json is not None:
        raise BadRequestException(
            f"Step {step_order}: {label} cannot define both body_template and body_json."
        )
