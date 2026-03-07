"""JSON output processing and contract validation for flow steps."""
from __future__ import annotations

import json
import re
from typing import Any

import jsonschema

from intric.main.exceptions import TypedIOValidationException

_FENCED_JSON_PATTERN = re.compile(
    r"^\s*```(?:json)?\s*(.*?)\s*```\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _parse_json_candidate(raw_text: str) -> dict[str, Any] | list[Any]:
    parsed = json.loads(raw_text)
    if not isinstance(parsed, (dict, list)):
        raise TypedIOValidationException(
            f"Expected JSON object or array, got {type(parsed).__name__}",
            code="typed_io_output_parse_failed",
        )
    return parsed


def _extract_embedded_json(raw_text: str) -> dict[str, Any] | list[Any] | None:
    decoder = json.JSONDecoder()
    for start_index, char in enumerate(raw_text):
        if char not in "{[":
            continue
        try:
            parsed, _end_index = decoder.raw_decode(raw_text[start_index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, (dict, list)):
            return parsed
    return None


def parse_json_output(raw_text: str) -> dict[str, Any] | list[Any]:
    """Parse LLM text as JSON. Raises TypedIOValidationException."""
    normalized = raw_text.strip()
    if normalized == "":
        raise TypedIOValidationException(
            "LLM response was empty; expected a JSON object or array.",
            code="typed_io_output_parse_failed",
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
            code="typed_io_output_parse_failed",
        ) from exc


def validate_against_contract(data: Any, schema: dict[str, Any], *, label: str) -> None:
    """Validate data against JSON Schema. Raises TypedIOValidationException."""
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        raise TypedIOValidationException(
            f"{label}: {exc.message}",
            code="typed_io_contract_violation",
        ) from exc


def validate_schema_syntax(schema: dict[str, Any], *, label: str) -> None:
    """Check schema is valid JSON Schema (publish-time)."""
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise TypedIOValidationException(
            f"{label} is not a valid JSON Schema: {exc.message}",
            code="typed_io_invalid_schema",
        ) from exc


def compile_validators(
    runtime_steps: list[Any],
) -> dict[tuple[str, int], jsonschema.Draft202012Validator]:
    """Pre-compile all step contracts once per run."""
    compiled: dict[tuple[str, int], jsonschema.Draft202012Validator] = {}
    for step in runtime_steps:
        if step.input_contract:
            compiled[("input", step.step_order)] = jsonschema.Draft202012Validator(
                step.input_contract
            )
        if step.output_contract:
            compiled[("output", step.step_order)] = jsonschema.Draft202012Validator(
                step.output_contract
            )
    return compiled
