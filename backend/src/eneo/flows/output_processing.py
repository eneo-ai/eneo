"""JSON output processing and contract validation for flow steps."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, cast

import jsonschema

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.json_types import JsonObject, JsonValue
from eneo.main.exceptions import TypedIOValidationException

_FENCED_JSON_PATTERN = re.compile(
    r"^\s*```(?:json)?\s*(.*?)\s*```\s*$",
    re.IGNORECASE | re.DOTALL,
)
_SCHEMA_TRAVERSAL_STOP_KEYS = frozenset({"$ref", "oneOf", "anyOf", "allOf"})

StructuredOutputValue = JsonObject | list[JsonValue]


# How many paths a diagnostic names; the counts beside them stay exact.
MAX_REPORTED_KEY_PATHS = 20


@dataclass(frozen=True, slots=True)
class KeyConformResult:
    dropped_paths: tuple[str, ...]
    renamed_count: int
    # (model-written path, contract path) of the first renames only.
    renamed_sample: tuple[tuple[str, str], ...]


@dataclass(slots=True)
class _KeyConformLog:
    dropped: list[str]
    renamed_count: int
    renamed_sample: list[tuple[str, str]]
    # Declared names by folded spelling, built once per object schema.
    declared_by_spelling: dict[int, dict[str, list[str]]]


def _parse_json_candidate(raw_text: str) -> StructuredOutputValue:
    parsed = json.loads(raw_text)
    if not isinstance(parsed, (dict, list)):
        raise TypedIOValidationException(
            f"Expected JSON object or array, got {type(parsed).__name__}",
            code=FlowApiErrorCode.TYPED_IO_OUTPUT_PARSE_FAILED.value,
        )
    return cast(StructuredOutputValue, parsed)


def _extract_embedded_json(raw_text: str) -> StructuredOutputValue | None:
    start = re.search(r"[\[{]", raw_text)
    if start is None:
        return None
    try:
        parsed, end = json.JSONDecoder().raw_decode(raw_text, start.start())
    except json.JSONDecodeError:
        # Trying later braces can turn a truncated document into a valid fragment.
        return None
    if re.search(r"[\[\]{}]", raw_text[end:]):
        return None
    return cast(StructuredOutputValue, parsed)


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
        path = "/" + "/".join(
            _json_pointer_token(str(part)) for part in exc.absolute_path
        )
        path = path[:400]
        rule = str(exc.validator)[:80]
        if rule == "type":
            detail = f"Value is not of type {exc.validator_value!r}."
        elif rule == "required":
            detail = exc.message
        elif rule == "additionalProperties":
            detail = "Additional properties are not allowed."
        else:
            detail = f"Value does not satisfy schema rule '{rule}'."
        raise TypedIOValidationException(
            f"{label} at {path}: {detail[:400]}",
            code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
            context={"json_pointer": path, "schema_rule": rule},
        ) from exc


def conform_keys_to_schema(
    data: StructuredOutputValue,
    schema: JsonObject,
) -> KeyConformResult:
    """Make model-output keys the contract's keys, in place.

    An undeclared key that differs from a missing required key only by canonically
    equivalent forms, combining marks and case (`bedömning` for `bedomning`) is that
    field written another way, so its value is kept under the declared name. Only a missing required key is a target:
    the contract already fails there, so a rename can only trade one failure for
    another. Every other key, respelled optional keys included, is treated as the
    pruning always did: dropped under an explicit additionalProperties:false, kept
    otherwise. Like the pruning, this reads properties and array items only:
    composition keywords, $ref, prefixItems and typed additionalProperties values
    are not walked.
    """
    log = _KeyConformLog(
        dropped=[], renamed_count=0, renamed_sample=[], declared_by_spelling={}
    )
    _conform_node(data, schema, "", log)
    return KeyConformResult(
        dropped_paths=tuple(log.dropped),
        renamed_count=log.renamed_count,
        renamed_sample=tuple(log.renamed_sample),
    )


def _conform_node(
    data: object,
    schema: object,
    path: str,
    log: _KeyConformLog,
) -> None:
    if not isinstance(schema, dict):
        return
    schema_node = cast(dict[str, object], schema)
    if _schema_has_traversal_stop(schema_node):
        return

    if isinstance(data, dict):
        data_object = cast(dict[object, object], data)
        _conform_object_keys(data_object, schema_node, path, log)
        return

    if isinstance(data, list):
        data_items = cast(list[object], data)
        item_schema = schema_node.get("items")
        if isinstance(item_schema, dict):
            typed_item_schema = cast(dict[str, object], item_schema)
            for index, item in enumerate(data_items):
                _conform_node(item, typed_item_schema, f"{path}/{index}", log)


def _schema_has_traversal_stop(schema: dict[str, object]) -> bool:
    return any(key in schema for key in _SCHEMA_TRAVERSAL_STOP_KEYS)


def _conform_object_keys(
    data: dict[object, object],
    schema: dict[str, object],
    path: str,
    log: _KeyConformLog,
) -> None:
    properties = schema.get("properties")
    typed_properties = (
        cast(dict[str, object], properties) if isinstance(properties, dict) else {}
    )

    _rename_respelled_keys(data, schema, typed_properties, path, log)

    if schema.get("additionalProperties") is False:
        allowed_keys = set(typed_properties)
        for key in list(data):
            if isinstance(key, str) and key not in allowed_keys:
                del data[key]
                log.dropped.append(f"{path}/{_json_pointer_token(key)}")

    for key, value in list(data.items()):
        if not isinstance(key, str):
            continue
        child_schema = typed_properties.get(key)
        if child_schema is None:
            continue
        _conform_node(
            value,
            child_schema,
            f"{path}/{_json_pointer_token(key)}",
            log,
        )


def _spelling(name: str) -> str:
    """The name after canonical decomposition, without combining marks, case-folded.

    Two names have the same spelling when they differ only by canonically
    equivalent forms (the Kelvin sign is `k`, the Angstrom sign `å`), combining
    marks and case. Compatibility forms, other letters, symbols and separators
    stay different: `①` is not `1`, `kø` is not `k` and `Andel (%)` is not `andel`.
    """
    decomposed = unicodedata.normalize("NFD", name)
    return "".join(
        character for character in decomposed if not unicodedata.combining(character)
    ).casefold()


def _rename_respelled_keys(
    data: dict[object, object],
    schema: dict[str, object],
    properties: dict[str, object],
    path: str,
    log: _KeyConformLog,
) -> None:
    """Rename a key that respells a missing required key.

    Declined when two declared keys share the spelling and when several keys claim
    one name. A declared key is never folded: it cannot be a respelling.
    """
    required = schema.get("required")
    if not isinstance(required, list):
        return
    missing = {
        name
        for name in cast(list[object], required)
        if isinstance(name, str) and name in properties and name not in data
    }
    if not missing:
        return

    declared_by_spelling = log.declared_by_spelling.get(id(properties))
    if declared_by_spelling is None:
        declared_by_spelling = dict[str, list[str]]()
        for name in properties:
            declared_by_spelling.setdefault(_spelling(name), []).append(name)
        log.declared_by_spelling[id(properties)] = declared_by_spelling

    spellings_by_declared: dict[str, list[str]] = {}
    for key in data:
        if not isinstance(key, str) or key in properties:
            continue
        declared = declared_by_spelling.get(_spelling(key), [])
        if len(declared) == 1 and declared[0] in missing:
            spellings_by_declared.setdefault(declared[0], []).append(key)
    renames = {
        spellings[0]: declared
        for declared, spellings in spellings_by_declared.items()
        if len(spellings) == 1
    }
    if not renames:
        return

    # Rebuild in order so a renamed key keeps its position.
    items = list(data.items())
    data.clear()
    for key, value in items:
        if isinstance(key, str) and key in renames:
            declared = renames[key]
            log.renamed_count += 1
            if log.renamed_count <= MAX_REPORTED_KEY_PATHS:
                log.renamed_sample.append(
                    (
                        f"{path}/{_json_pointer_token(key)}",
                        f"{path}/{_json_pointer_token(declared)}",
                    )
                )
            data[declared] = value
        else:
            data[key] = value


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


def schema_yields_top_level_object(schema: dict[str, Any]) -> bool:
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        return raw_type == "object"
    if isinstance(raw_type, list):
        declared = {
            item for item in cast(list[object], raw_type) if isinstance(item, str)
        }
        return "object" in declared and "array" not in declared
    if isinstance(schema.get("properties"), dict):
        return True
    if "items" in schema:
        return False
    return False


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
