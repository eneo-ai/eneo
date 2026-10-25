"""JSON output processing and contract validation for flow steps."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast
from urllib.parse import unquote

import jsonschema
from jsonschema.protocols import Validator
from jsonschema.validators import validator_for
from referencing import Resource
from referencing.jsonschema import DRAFT202012, Schema

from eneo.flows.domain.schema_engine import (
    CONTRACT_FAILURES,
    LOCAL_SCHEMA_REGISTRY,
    ContractFinding,
    ContractNotEvaluable,
    SchemaValidator,
    build_schema_validator,
    check_metaschema,
    dialect_of,
    evaluate_contract,
)
from eneo.flows.domain.strict_schema_limits import (
    COMMON_STRICT_SCHEMA_LIMITS,
    StrictSchemaLimits,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import (
    CONTRACT_VIOLATION_POINTER_MAX_LENGTH,
    ContractSide,
)
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


_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


class ContractUnevaluable(TypedIOValidationException):
    """No data can be judged against the contract: the fault is the schema's,
    whatever the data is."""


def _unevaluable(label: str) -> ContractUnevaluable:
    return ContractUnevaluable(
        f"{label}: the contract cannot be evaluated.",
        code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
    )


def refuse_unknown_dialect(schema: Mapping[str, object], *, label: str) -> None:
    """Raise ContractUnevaluable for a schema that names, in ``$schema``, a
    dialect the validator library does not have: checked by the default
    draft's rules, it would be judged by other rules than its own. A schema
    that names none is read as the default draft and is not refused.

    The checks of a tool's input schema ask this. A step's contract is not
    asked: a write refuses every dialect but the current one, and a contract
    stored before that rule is read as ``dialect_of`` reads it.
    """
    if not isinstance(schema.get("$schema"), str):
        return
    try:
        # The library's registry answers a name it has with that dialect,
        # whatever default it is given, and a name it does not have with the
        # default.
        known = any(
            validator_for(schema, default=default) is not default
            for default in (jsonschema.Draft202012Validator, jsonschema.Draft7Validator)
        )
    except ValueError as exc:  # a name that is no URI
        raise _unevaluable(label) from exc
    if not known:
        raise _unevaluable(label)


def refuse_unevaluable_contract(schema: Mapping[str, object], *, label: str) -> None:
    """Raise ContractUnevaluable for a schema that is not a valid schema of the
    draft it names. ``evaluate_contract`` makes this check before it reads
    any data; a reference that does not resolve inside the schema is found
    only when data reaches it."""
    try:
        check_metaschema(schema, dialect_of(schema))
    except CONTRACT_FAILURES as exc:
        raise _unevaluable(label) from exc


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


def _nested_too_deep() -> TypedIOValidationException:
    return TypedIOValidationException(
        "LLM response is nested too deep to be read as JSON.",
        code=FlowApiErrorCode.TYPED_IO_OUTPUT_PARSE_FAILED.value,
    )


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
    except RecursionError:
        # Not the embedded-JSON extraction below: it would decode the same
        # nesting again.
        raise _nested_too_deep() from None
    except (json.JSONDecodeError, ValueError) as exc:
        try:
            embedded = _extract_embedded_json(normalized)
        except RecursionError:
            raise _nested_too_deep() from None
        if embedded is not None:
            return embedded
        raise TypedIOValidationException(
            f"LLM response is not valid JSON: {exc}",
            code=FlowApiErrorCode.TYPED_IO_OUTPUT_PARSE_FAILED.value,
        ) from exc


def validate_against_contract(
    data: Any,
    schema: dict[str, Any],
    *,
    label: str,
    side: ContractSide | None = None,
) -> None:
    """Validate data against JSON Schema. Raises TypedIOValidationException:
    ContractUnevaluable when the schema itself cannot be evaluated.

    A run boundary passes `side`; the context then carries the facts a terminal
    run error keeps (FlowRunContractViolation, which owns their bounds): the rule
    and the RFC 6901 pointer ("" is the root), cut before any key that comes from
    the data. The message keeps the full location.
    """
    raise_contract_finding(
        evaluate_contract(data, schema), schema, label=label, side=side
    )


def raise_contract_finding(
    finding: ContractFinding,
    schema: Schema,
    *,
    label: str,
    side: ContractSide | None = None,
) -> None:
    """Raise for ``finding`` (from ``evaluate_contract`` on ``schema``) what
    ``validate_against_contract`` raises: ContractUnevaluable, or the
    violation with its typed context; nothing for None."""
    if finding is None:
        return
    if isinstance(finding, ContractNotEvaluable):
        raise _unevaluable(label)
    pointer = "".join("/" + _json_pointer_token(str(part)) for part in finding.path)
    path = (pointer or "/")[:CONTRACT_VIOLATION_POINTER_MAX_LENGTH]
    context: dict[str, object] = {
        "json_pointer": _contract_named_pointer(schema, finding.path)
    }
    if finding.rule is not None:
        context["schema_rule"] = finding.rule
    if side is not None:
        context["contract_side"] = side
    raise TypedIOValidationException(
        f"{label} at {path}: {finding.detail[:400]}",
        code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
        context=context,
    )


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


def _crawled_resolver(resource: Resource[Schema]):
    """A resolver over `resource` alone, crawled once: a lookup on an uncrawled
    registry crawls the document again."""
    uri = resource.id() or ""
    return LOCAL_SCHEMA_REGISTRY.with_resource(uri, resource).crawl().resolver(uri)


def _contract_named_pointer(schema: Schema, path: Iterable[str | int]) -> str:
    """The RFC 6901 pointer to the deepest part of `path` that the contract names.

    Keeps declared property names (`properties`, `required`) and array indices and
    stops before a key that comes from the data (additionalProperties,
    patternProperties, unevaluatedProperties), or that the contract reaches only
    through composition. A terminal run error stores this pointer, and a person's
    data must not become part of it.
    """
    tokens: list[str] = []
    try:
        resolver = _crawled_resolver(
            Resource.from_contents(schema, default_specification=DRAFT202012)
        )
        node: object = schema
        for part in path:
            step = _named_step(node, part, lambda ref: resolver.lookup(ref).contents)
            if step is None:
                break
            node = step[0]
            tokens.append(_json_pointer_token(str(part)))
    except CONTRACT_FAILURES:
        pass
    return "".join("/" + token for token in tokens)


def _named_step(
    node: object,
    part: str | int,
    lookup: Callable[[str], object],
) -> tuple[object] | None:
    """The subschema after `part` (None when unknown), or None when not named.

    Follows a chain of `$ref`s until a schema declares `part`; a reference already
    followed in this chain ends it, so a cycle stops and a finite chain never does.
    """
    chain: list[dict[str, object]] = []
    followed: set[str] = set()
    current = node
    while isinstance(current, dict):
        schema = cast(dict[str, object], current)
        chain.append(schema)
        if isinstance(part, int):
            prefix = schema.get("prefixItems")
            items = schema.get("items")
            if isinstance(prefix, list) and part < len(cast(list[object], prefix)):
                return (cast(list[object], prefix)[part],)
            if isinstance(items, dict):
                return (cast(dict[str, object], items),)
        else:
            properties = schema.get("properties")
            if isinstance(properties, dict) and part in properties:
                return (cast(dict[str, object], properties)[part],)
        reference = schema.get("$ref")
        if not isinstance(reference, str) or reference in followed:
            break
        followed.add(reference)
        current = lookup(reference)
    if isinstance(part, int):
        return (None,)
    named = any(
        isinstance(required, list) and part in cast(list[object], required)
        for required in (schema.get("required") for schema in chain)
    )
    return (None,) if named else None


def validate_schema_syntax(
    schema: dict[str, Any], *, label: str, retained: bool = False
) -> None:
    """Check schema is valid JSON Schema (publish-time).

    A contract is a 2020-12 document that never leaves itself: no $id, no other
    $schema, and every reference resolves to a schema of the same document. A
    `retained` contract, saved earlier and left as it was, keeps the rules it was
    saved under: only the metaschema is checked, and the registry still refuses
    every retrieval when it runs.
    """
    try:
        check_metaschema(schema, jsonschema.Draft202012Validator)
    except jsonschema.SchemaError as exc:
        raise TypedIOValidationException(
            f"{label} is not a valid JSON Schema: {exc.message}",
            code=FlowApiErrorCode.TYPED_IO_INVALID_SCHEMA.value,
        ) from exc
    except CONTRACT_FAILURES as exc:
        raise TypedIOValidationException(
            f"{label} is not a valid JSON Schema: it cannot be checked.",
            code=FlowApiErrorCode.TYPED_IO_INVALID_SCHEMA.value,
        ) from exc
    issue = None if retained else _self_containment_issue(schema)
    if issue is not None:
        pointer, rule, detail = issue
        raise TypedIOValidationException(
            f"{label} at {pointer}: {detail}",
            code=FlowApiErrorCode.TYPED_IO_INVALID_SCHEMA.value,
            context={"json_pointer": pointer, "schema_rule": rule},
        )


# The drafts a pasted schema may be converted from: those whose type checker is that of
# 2020-12 (jsonschema's draft6_type_checker redefines "integer" so 2.0 is one, and later
# drafts inherit it; drafts 3 and 4 keep the older rule and are declined).
_CONVERTIBLE_DRAFTS = (
    jsonschema.Draft6Validator,
    jsonschema.Draft7Validator,
    jsonschema.Draft201909Validator,
)
# The only keywords a pasted schema may use and be converted. Each has the same function
# in its draft's VALIDATORS map as in 2020-12's, or is an annotation none of them runs
# (test_the_convertible_keywords_run_the_same_in_every_supported_draft checks the maps).
# `items` differs only in its array form, which fails the 2020-12 metaschema and is
# declined by its check; `if` is missing from draft 6, so a draft-6 `if` is declined. Anything else, above all $id, $ref, $anchor, definitions, $defs and
# dependencies, could be read differently by 2020-12 and is never converted.
_CONVERTIBLE_KEYWORDS = frozenset(
    "type properties required enum const items additionalProperties patternProperties "
    "propertyNames minimum maximum exclusiveMinimum exclusiveMaximum multipleOf "
    "minLength maxLength pattern format minItems maxItems uniqueItems minProperties "
    "maxProperties allOf anyOf oneOf not if then else title description default "
    "examples readOnly writeOnly".split()
)


def normalize_pasted_schema(schema: JsonObject) -> JsonObject:
    """A pasted draft 6, 7 or 2019-09 schema as a 2020-12 contract, when it can be one.

    It is converted, by dropping its top-level $schema, only if every schema node
    uses nothing but _CONVERTIBLE_KEYWORDS, which every one of those drafts reads as
    2020-12 does. Anything else, a 2020-12 or $schema-less schema included, is
    returned as it came, for the contract rules to accept or refuse.
    """
    draft = _pasted_draft(schema)
    if draft is None:
        return schema
    stripped = {key: value for key, value in schema.items() if key != "$schema"}
    try:
        # The walk below reads only what the 2020-12 metaschema accepts.
        check_metaschema(stripped, jsonschema.Draft202012Validator)
    except CONTRACT_FAILURES:
        return schema
    if all(
        _reads_alike(node, draft)
        for _, node in _schema_nodes(stripped)
        if isinstance(node, dict)
    ):
        return stripped
    return schema


def _pasted_draft(schema: JsonObject) -> type[Validator] | None:
    uri = schema.get("$schema")
    if not isinstance(uri, str):
        return None
    try:
        # Draft 3 is the default so that an unknown URI and draft 3 both come back as None.
        draft = validator_for(schema, default=jsonschema.Draft3Validator)
    except ValueError:  # a $schema that is not a URI at all
        return None
    return draft if draft in _CONVERTIBLE_DRAFTS else None


def _reads_alike(node: dict[str, Any], draft: type[Validator]) -> bool:
    current = jsonschema.Draft202012Validator.VALIDATORS
    return all(
        key in _CONVERTIBLE_KEYWORDS
        and (key == "items" or draft.VALIDATORS.get(key) is current.get(key))
        for key in node
    )


def _self_containment_issue(schema: dict[str, Any]) -> tuple[str, str, str] | None:
    """Where a 2020-12 contract leaves itself first, as (pointer, keyword, reason)."""
    positions = list(_schema_nodes(schema))
    nodes = [(path, node) for path, node in positions if isinstance(node, dict)]
    references = False
    for path, node in nodes:
        if "$id" in node:
            return f"{path}/$id", "$id", "$id is not allowed in a contract."
        if node.get("$schema", _SCHEMA_DIALECT) != _SCHEMA_DIALECT:
            return f"{path}/$schema", "$schema", f"$schema must be {_SCHEMA_DIALECT}."
        references = references or "$ref" in node or "$dynamicRef" in node
    if not references:
        # Nothing can leave the contract, so there is nothing to crawl or resolve.
        return None
    schema_nodes = {id(node) for _, node in nodes}
    # A boolean has no identity of its own: it is a schema by its pointer.
    boolean_pointers = {path for path, node in positions if isinstance(node, bool)}
    # Crawled once here: a lookup on an uncrawled registry crawls the document again.
    resolver = _crawled_resolver(DRAFT202012.create_resource(schema))

    def points_at_schema(target: object) -> bool:
        if not (isinstance(target, str) and target.startswith("#")):
            return False
        try:
            found = resolver.lookup(target).contents
        except CONTRACT_FAILURES:
            return False
        if isinstance(found, bool):
            return unquote(target[1:]) in boolean_pointers
        return id(found) in schema_nodes

    for path, node in nodes:
        for keyword in ("$ref", "$dynamicRef"):
            if keyword in node and not points_at_schema(node[keyword]):
                return (
                    f"{path}/{keyword}",
                    keyword,
                    f"{keyword} must point to a schema inside this contract.",
                )
    return None


def _schema_nodes(
    schema: dict[str, Any] | bool, path: str = ""
) -> Iterator[tuple[str, dict[str, Any] | bool]]:
    """Every schema position of a 2020-12 document with its JSON pointer.

    A keyword is asked alone which of its values are schemas, so a value that is
    only data (`default: true` beside `items: true`) is never taken for one.
    """
    yield path, schema
    if isinstance(schema, bool):
        return
    for key, value in schema.items():
        children = {id(child) for child in DRAFT202012.subresources_of({key: value})}
        child_path = f"{path}/{_json_pointer_token(key)}"
        if id(value) in children:
            yield from _schema_nodes(value, child_path)
        elif isinstance(value, dict):
            for name, child in cast(dict[str, Any], value).items():
                if id(child) in children:
                    yield from _schema_nodes(
                        child, f"{child_path}/{_json_pointer_token(name)}"
                    )
        elif isinstance(value, list):
            for index, child in enumerate(cast(list[Any], value)):
                if id(child) in children:
                    yield from _schema_nodes(child, f"{child_path}/{index}")


# A tuple, not a set: a declared type list is unhashable.
PRIMITIVE_FIELD_TYPES = ("string", "number", "integer", "boolean")

# What a schema may carry to be sent as `strict: true`: nothing but these, each in the
# shape _strict_node_violation names. A keyword outside this set is never read as one.
_STRICT_RESPONSE_KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "const",
        "title",
        "description",
    }
)

StrictResponseRule = Literal[
    "schema_not_object",
    "boolean_schema",
    "keyword_outside_grammar",
    "type_outside_grammar",
    "root_not_object",
    "structure_mismatch",
    "object_open",
    "required_mismatch",
    "enum_invalid",
    "enum_with_const",
    "enum_type_mismatch",
    "const_invalid",
    "const_type_mismatch",
    "annotation_invalid",
    "contract_unreadable",
    "nesting_depth_exceeded",
    "property_count_exceeded",
    "enum_value_count_exceeded",
    "enum_string_size_exceeded",
    "string_size_exceeded",
]


def _is_scalar(value: object) -> bool:
    """A string, bool, int or finite float: JSON has no NaN or infinity."""
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, (str, int, bool))


def _fits_primitive(value: object, primitive: object) -> bool:
    """Whether a value is one the primitive type admits (a bool is no number)."""
    if primitive == "string":
        return isinstance(value, str)
    if primitive == "boolean":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if primitive == "integer":
        return isinstance(value, int)
    return primitive == "number" and isinstance(value, (int, float))


def _scalar_size(value: str | int | float | bool) -> int:
    return len(value) if isinstance(value, str) else len(json.dumps(value))


def _strict_node_violation(
    node: object, *, is_root: bool, enum_values_left: int
) -> tuple[str, StrictResponseRule] | None:
    """The first rule one schema node breaks, as (keyword suffix, rule); None if none.

    The suffix is "" for the node itself or "/<keyword>" for the keyword at fault.
    """
    if isinstance(node, bool):
        return "", "boolean_schema"
    if not isinstance(node, dict):
        return "", "schema_not_object"
    schema = cast(dict[str, Any], node)
    for key in schema:
        if key not in _STRICT_RESPONSE_KEYWORDS:
            return f"/{_json_pointer_token(str(key))}", "keyword_outside_grammar"
    declared = schema.get("type")
    if isinstance(declared, list):
        members = cast(list[object], declared)
        primitives = [m for m in members if m in PRIMITIVE_FIELD_TYPES]
        is_nullable_primitive = (
            len(members) == 2 and len(primitives) == 1 and "null" in members
        )
        kind = "leaf" if is_nullable_primitive else None
        primitive = primitives[0] if is_nullable_primitive else None
    elif declared in PRIMITIVE_FIELD_TYPES:
        kind = "leaf"
        primitive = declared
    else:
        kind = declared if declared in ("object", "array") else None
        primitive = None
    if kind is None:
        return "", "type_outside_grammar"
    if is_root and kind != "object":
        return "", "root_not_object"
    structural = {
        "object": {"properties", "required", "additionalProperties"},
        "array": {"items"},
        "leaf": set[str](),
    }
    for keyword in ("properties", "required", "additionalProperties", "items"):
        if keyword in schema and keyword not in structural[kind]:
            return "", "structure_mismatch"
    if kind != "leaf" and ("enum" in schema or "const" in schema):
        return "", "structure_mismatch"
    if kind == "object":
        if schema.get("additionalProperties") is not False:
            return "", "object_open"
        properties = cast(object, schema.get("properties"))
        if not isinstance(properties, dict) or not properties:
            return "", "structure_mismatch"
        names = cast(dict[str, object], properties)
        required = schema.get("required")
        if (
            not isinstance(required, list)
            or not all(isinstance(name, str) for name in cast(list[object], required))
            or len(cast(list[object], required)) != len(names)
            or set(cast(list[str], required)) != set(names)
        ):
            return "", "required_mismatch"
    if kind == "array" and "items" not in schema:
        return "", "structure_mismatch"
    if "enum" in schema and "const" in schema:
        # Either alone is read; both together are rejected rather than reconciled.
        return "", "enum_with_const"
    if "enum" in schema:
        values = schema["enum"]
        if not isinstance(values, list) or not values:
            return "", "enum_invalid"
        # Before the values are read or hashed: an over-limit enum builds nothing.
        if len(cast(list[object], values)) > enum_values_left:
            return "", "enum_value_count_exceeded"
        if not all(_is_scalar(v) for v in cast(list[object], values)):
            return "", "enum_invalid"
        if len(set(cast(list[Any], values))) != len(cast(list[object], values)):
            return "", "enum_invalid"
        if not all(_fits_primitive(v, primitive) for v in cast(list[Any], values)):
            return "", "enum_type_mismatch"
    if "const" in schema:
        if not _is_scalar(schema["const"]):
            return "", "const_invalid"
        if not _fits_primitive(schema["const"], primitive):
            return "", "const_type_mismatch"
    if any(
        key in schema and not isinstance(schema[key], str)
        for key in ("title", "description")
    ):
        return "", "annotation_invalid"
    return None


def first_strict_response_violation(
    contract: object,
    limits: StrictSchemaLimits = COMMON_STRICT_SCHEMA_LIMITS,
) -> tuple[str, StrictResponseRule] | None:
    """The first reason a contract may not be sent as `strict: true`, or None if it may.

    An allowlist recognizer: only the shapes _strict_node_violation names are eligible,
    and a closed object with every property required is the one object shape. Beside
    the shape, the schema must fit the provider `limits` (nesting levels, total
    properties, enum values and string sizes; see strict_schema_limits). It reads the
    contract alone, never mutates it, and never raises: a contract it cannot walk is a
    violation. Violations come in document order; a node's shape rules come before its
    limit checks, except that an enum's value count is checked before its values are
    read. Nothing calls it yet.
    """
    properties_seen = enum_values_seen = string_chars_seen = 0
    ancestors: list[tuple[str, int]] = []
    pointer = ""
    try:
        for pointer, node in _schema_nodes(cast(Any, contract)):
            while ancestors and not pointer.startswith(ancestors[-1][0] + "/"):
                ancestors.pop()
            if ancestors and pointer == f"{ancestors[-1][0]}/additionalProperties":
                # The literal false its object already passed, not a schema.
                continue
            violation = _strict_node_violation(
                node,
                is_root=not pointer,
                enum_values_left=limits.max_enum_values - enum_values_seen,
            )
            if violation is not None:
                suffix, rule = violation
                return pointer + suffix, rule
            schema = cast(dict[str, Any], node)
            parent_levels = ancestors[-1][1] if ancestors else 0
            is_container = schema.get("type") in ("object", "array")
            levels = parent_levels + int(is_container)
            ancestors.append((pointer, levels))
            if levels > limits.max_nesting_levels:
                return pointer, "nesting_depth_exceeded"
            if schema.get("type") == "object":
                names = cast(dict[str, Any], schema["properties"])
                properties_seen += len(names)
                string_chars_seen += sum(len(name) for name in names)
                if properties_seen > limits.max_properties:
                    return pointer, "property_count_exceeded"
            if "enum" in schema:
                values = cast(list[str | int | float | bool], schema["enum"])
                enum_values_seen += len(values)
                if (
                    len(values) > limits.enum_size_checked_above_values
                    and sum(len(v) for v in values if isinstance(v, str))
                    > limits.max_enum_string_chars
                ):
                    return pointer, "enum_string_size_exceeded"
                string_chars_seen += sum(_scalar_size(v) for v in values)
            if "const" in schema:
                string_chars_seen += _scalar_size(schema["const"])
            if string_chars_seen > limits.max_total_string_chars:
                return pointer, "string_size_exceeded"
    except CONTRACT_FAILURES:
        return pointer, "contract_unreadable"
    return None


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
) -> dict[tuple[str, int], SchemaValidator]:
    """Pre-compile all step contracts once per run."""
    compiled: dict[tuple[str, int], SchemaValidator] = {}
    for step in runtime_steps:
        for direction, contract in (
            ("input", step.input_contract),
            ("output", step.output_contract),
        ):
            if contract is None:
                continue
            key = (direction, step.step_order)
            try:
                compiled[key] = build_schema_validator(contract)
            except CONTRACT_FAILURES as exc:
                raise _unevaluable(f"Step {step.step_order} {direction}") from exc
    return compiled
