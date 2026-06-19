"""JSON output processing and contract validation for flow steps."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, cast

import jsonschema

from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.json_types import JsonObject, JsonValue
from intric.main.exceptions import TypedIOValidationException

_FENCED_JSON_PATTERN = re.compile(
    r"^\s*```(?:json)?\s*(.*?)\s*```\s*$",
    re.IGNORECASE | re.DOTALL,
)
_SCHEMA_TRAVERSAL_STOP_KEYS = frozenset({"$ref", "oneOf", "anyOf", "allOf"})

StructuredOutputValue = JsonObject | list[JsonValue]


@dataclass(frozen=True, slots=True)
class StrictSchemaPruneResult:
    dropped_paths: tuple[str, ...]


def _parse_json_candidate(raw_text: str) -> StructuredOutputValue:
    parsed = json.loads(raw_text)
    if not isinstance(parsed, (dict, list)):
        raise TypedIOValidationException(
            f"Expected JSON object or array, got {type(parsed).__name__}",
            code=FlowApiErrorCode.TYPED_IO_OUTPUT_PARSE_FAILED.value,
        )
    return cast(StructuredOutputValue, parsed)


def _extract_embedded_json(raw_text: str) -> StructuredOutputValue | None:
    decoder = json.JSONDecoder()
    for start_index, char in enumerate(raw_text):
        if char not in "{[":
            continue
        try:
            parsed, _end_index = decoder.raw_decode(raw_text[start_index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, (dict, list)):
            return cast(StructuredOutputValue, parsed)
    return None


def parse_json_output(raw_text: str) -> StructuredOutputValue:
    """Parse LLM text as JSON. Raises TypedIOValidationException."""
    normalized = raw_text.strip()
    if normalized == "":
        raise TypedIOValidationException(
            "LLM response was empty; expected a JSON object or array.",
            code=FlowApiErrorCode.TYPED_IO_OUTPUT_PARSE_FAILED.value,
        )

    fenced_match = _FENCED_JSON_PATTERN.match(normalized)
    if fenced_match is not None:
        normalized = fenced_match.group(1).strip()

    try:
        return _parse_json_candidate(normalized)
    except (json.JSONDecodeError, ValueError) as exc:
        embedded = _extract_embedded_json(normalized)
        if embedded is not None:
            return embedded
        raise TypedIOValidationException(
            f"LLM response is not valid JSON: {exc}",
            code=FlowApiErrorCode.TYPED_IO_OUTPUT_PARSE_FAILED.value,
        ) from exc


def validate_against_contract(data: Any, schema: dict[str, Any], *, label: str) -> None:
    """Validate data against JSON Schema. Raises TypedIOValidationException."""
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        raise TypedIOValidationException(
            f"{label}: {exc.message}",
            code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
        ) from exc


def prune_extras_to_strict_schema(
    data: StructuredOutputValue,
    schema: JsonObject,
) -> StrictSchemaPruneResult:
    """Drop only undeclared model-output keys under explicit additionalProperties:false."""
    dropped_paths: list[str] = []
    _prune_extras_to_strict_schema_node(data, schema, "", dropped_paths)
    return StrictSchemaPruneResult(dropped_paths=tuple(dropped_paths))


def _prune_extras_to_strict_schema_node(
    data: object,
    schema: object,
    path: str,
    dropped_paths: list[str],
) -> None:
    if not isinstance(schema, dict):
        return
    schema_node = cast(dict[str, object], schema)
    if _schema_has_traversal_stop(schema_node):
        return

    if isinstance(data, dict):
        data_object = cast(dict[object, object], data)
        _prune_object_extras(data_object, schema_node, path, dropped_paths)
        return

    if isinstance(data, list):
        data_items = cast(list[object], data)
        item_schema = schema_node.get("items")
        if isinstance(item_schema, dict):
            typed_item_schema = cast(dict[str, object], item_schema)
            for index, item in enumerate(data_items):
                _prune_extras_to_strict_schema_node(
                    item,
                    typed_item_schema,
                    f"{path}/{index}",
                    dropped_paths,
                )


def _schema_has_traversal_stop(schema: dict[str, object]) -> bool:
    return any(key in schema for key in _SCHEMA_TRAVERSAL_STOP_KEYS)


def _prune_object_extras(
    data: dict[object, object],
    schema: dict[str, object],
    path: str,
    dropped_paths: list[str],
) -> None:
    properties = schema.get("properties")
    typed_properties = (
        cast(dict[str, object], properties) if isinstance(properties, dict) else {}
    )

    if schema.get("additionalProperties") is False:
        allowed_keys = set(typed_properties)
        for key in list(data):
            if isinstance(key, str) and key not in allowed_keys:
                del data[key]
                dropped_paths.append(f"{path}/{_json_pointer_token(key)}")

    for key, value in list(data.items()):
        if not isinstance(key, str):
            continue
        child_schema = typed_properties.get(key)
        if child_schema is None:
            continue
        _prune_extras_to_strict_schema_node(
            value,
            child_schema,
            f"{path}/{_json_pointer_token(key)}",
            dropped_paths,
        )


def _json_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def validate_schema_syntax(schema: dict[str, Any], *, label: str) -> None:
    """Check schema is valid JSON Schema (publish-time)."""
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise TypedIOValidationException(
            f"{label} is not a valid JSON Schema: {exc.message}",
            code=FlowApiErrorCode.TYPED_IO_INVALID_SCHEMA.value,
        ) from exc


def schema_expects_structured(schema: dict[str, Any]) -> bool:
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        return raw_type in {"object", "array"}
    if isinstance(raw_type, list):
        return any(
            item in {"object", "array"}
            for item in cast(list[object], raw_type)
            if isinstance(item, str)
        )
    return isinstance(schema.get("properties"), dict) or "items" in schema


def compile_validators(
    runtime_steps: list[Any],
) -> dict[tuple[str, int], jsonschema.Draft202012Validator]:
    """Pre-compile all step contracts once per run."""
    compiled: dict[tuple[str, int], jsonschema.Draft202012Validator] = {}
    for step in runtime_steps:
        if step.input_contract is not None:
            compiled[("input", step.step_order)] = jsonschema.Draft202012Validator(
                step.input_contract
            )
        if step.output_contract is not None:
            compiled[("output", step.step_order)] = jsonschema.Draft202012Validator(
                step.output_contract
            )
    return compiled
