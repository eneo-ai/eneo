"""The JSON Schema engine every Flow check of data against a schema uses.

It imports jsonschema and referencing and nothing of Eneo, so that the child
process that checks a tool step's arguments (runtime/tool_argument_check.py)
does not import what output_processing imports.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from collections.abc import Generator, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, NoReturn, Protocol, cast

import jsonschema
from jsonschema.exceptions import UnknownType
from jsonschema.protocols import Validator
from jsonschema.validators import validator_for
from referencing import Registry
from referencing.exceptions import NoSuchResource, Unresolvable
from referencing.jsonschema import Schema


def _refuse_schema_retrieval(uri: str) -> NoReturn:
    raise NoSuchResource(ref=uri)


LOCAL_SCHEMA_REGISTRY = Registry[Schema](retrieve=_refuse_schema_retrieval)
# What referencing and jsonschema raise, instead of a ValidationError, for a contract
# they cannot evaluate: no metaschema fit, an unresolved or cyclic reference, a JSON
# pointer that is not an array index, a draft-03 crawl of a malformed keyword, and a
# schema the metaschema check never read (a $ref into `default`) with a null, unknown
# or unhashable `type` or `$schema`, an invalid numerical constraint, and an
# expression `re` cannot compile.
CONTRACT_FAILURES = (
    ZeroDivisionError,
    re.error,
    jsonschema.SchemaError,
    UnknownType,
    Unresolvable,
    RecursionError,
    AttributeError,
    TypeError,
    ValueError,
)


class SchemaValidator(Protocol):
    def validate(self, instance: Any) -> None: ...

    def iter_errors(self, instance: Any) -> Iterator[jsonschema.ValidationError]: ...

    def evolve(self, *, schema: Schema) -> "SchemaValidator": ...


def dialect_of(schema: Schema) -> type[Validator]:
    """The draft a stored contract names, chosen as jsonschema.validate chose it."""
    if isinstance(schema, dict) and isinstance(schema.get("$schema"), str):
        return validator_for(schema, default=jsonschema.Draft202012Validator)
    return jsonschema.Draft202012Validator


def build_schema_validator(
    schema: Schema,
    *,
    format_checker: jsonschema.FormatChecker | None = None,
) -> SchemaValidator:
    """All Flow schemas resolve references without external retrieval."""
    return cast(
        SchemaValidator,
        dialect_of(schema)(
            schema, registry=LOCAL_SCHEMA_REGISTRY, format_checker=format_checker
        ),
    )


# The drafts whose "$ref" stands for its whole schema object: a keyword beside
# it is not evaluated.
_REF_IGNORES_SIBLINGS: frozenset[type[Validator]] = frozenset(
    {
        jsonschema.Draft3Validator,
        jsonschema.Draft4Validator,
        jsonschema.Draft6Validator,
        jsonschema.Draft7Validator,
    }
)


def ref_ignores_siblings(schema: Mapping[str, object]) -> bool:
    """Whether validating against ``schema`` reads none of the keywords beside
    its top-level ``$ref``: it has one, and the draft it names (read as the
    validator reads it) is 3, 4, 6 or 7."""
    return (
        schema.get("$ref") is not None and dialect_of(schema) in _REF_IGNORES_SIBLINGS
    )


@contextmanager
def _panic_as_recursion() -> Generator[None]:
    """Report the recursion limit tripping inside rpds as a RecursionError.

    rpds panics there, and pyo3 raises a BaseException that no `except Exception`
    catches.
    """
    try:
        yield
    except BaseException as exc:
        if type(exc).__module__ != "pyo3_runtime":
            raise
        raise RecursionError("recursion limit reached in the reference engine") from exc


# How many accepted schemas the metaschema check remembers, least recently
# used forgotten first. An entry is a digest, about 100 bytes.
METASCHEMA_VERDICTS_MAX = 1024
# (dialect, sha256 of the schema's repr) of each schema the check
# accepted. A refusal is not remembered: its message holds part of the schema.
_metaschema_verdicts: OrderedDict[tuple[type[Validator], bytes], None] = OrderedDict()
# Draft saves check on the event loop and step-kind answers in threads.
_metaschema_verdicts_lock = threading.Lock()


def _content_key(
    schema: Schema, dialect: type[Validator]
) -> tuple[type[Validator], bytes] | None:
    """``schema``'s content in its own key order, which the check reads it in.
    Its repr, unlike its JSON text, tells a list from a tuple and a str key
    from an int key, as the check does. None when it has none (nested too
    deep), and the schema is checked as if never seen."""
    try:
        text = repr(schema)
    except Exception:
        return None
    return dialect, hashlib.sha256(text.encode()).digest()


def check_metaschema(schema: Schema, dialect: type[Validator]) -> None:
    """Raise SchemaError for a schema that is not one of ``dialect``, and
    RecursionError for one nested too deep to check, also when the limit
    trips inside rpds, so that every caller can refuse it as a typed
    failure. A schema with the content of one accepted before is accepted
    without a check."""
    key = _content_key(schema, dialect)
    if key is not None:
        with _metaschema_verdicts_lock:
            if key in _metaschema_verdicts:
                _metaschema_verdicts.move_to_end(key)
                return
    _check_metaschema(schema, dialect)
    if key is not None:
        with _metaschema_verdicts_lock:
            _metaschema_verdicts[key] = None
            if len(_metaschema_verdicts) > METASCHEMA_VERDICTS_MAX:
                _metaschema_verdicts.popitem(last=False)


def _check_metaschema(schema: Schema, dialect: type[Validator]) -> None:
    validator = build_schema_validator(
        dialect.META_SCHEMA, format_checker=dialect.FORMAT_CHECKER
    )
    try:
        with _panic_as_recursion():
            validator.validate(schema)
    except jsonschema.ValidationError as exc:
        raise jsonschema.SchemaError.create_from(exc) from exc


@dataclass(frozen=True, slots=True)
class ContractViolation:
    """The first error of data against a contract, as plain data that crosses
    a process boundary."""

    # Where in the data, from the root (the validator's absolute_path).
    path: tuple[str | int, ...]
    # The keyword that failed; None for a false subschema, which has none.
    rule: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class ContractNotEvaluable:
    """The contract cannot be evaluated, whatever the data is."""


ContractFinding = ContractViolation | ContractNotEvaluable | None


def _violation(error: jsonschema.ValidationError) -> ContractViolation:
    rule = error.validator if isinstance(error.validator, str) else None
    if rule == "type":
        detail = f"Value is not of type {error.validator_value!r}."
    elif rule == "required":
        detail = error.message
    elif rule == "additionalProperties":
        detail = "Additional properties are not allowed."
    else:
        detail = f"Value does not satisfy schema rule '{rule}'."
    return ContractViolation(path=tuple(error.absolute_path), rule=rule, detail=detail)


def evaluate_contract(data: object, schema: Schema) -> ContractFinding:
    """The first error of ``data`` against ``schema``, ContractNotEvaluable
    when the schema is not a valid schema of the draft it names or cannot be
    evaluated against ``data``, None when ``data`` fits."""
    try:
        check_metaschema(schema, dialect_of(schema))
        with _panic_as_recursion():
            build_schema_validator(schema).validate(data)
    except jsonschema.ValidationError as exc:
        return _violation(exc)
    except CONTRACT_FAILURES:
        return ContractNotEvaluable()
    return None


def property_schema(schema: Mapping[str, object], name: str) -> Schema | None:
    """The subschema that the top-level ``properties`` of ``schema`` gives
    for ``name``, which validating an object that holds ``name`` always
    applies to its value. None when validation reads none: ``properties`` is
    absent or no object, does not name ``name``, or stands beside a
    top-level ``$ref`` that hides its siblings (``ref_ignores_siblings``)."""
    properties = schema.get("properties")
    if ref_ignores_siblings(schema) or not isinstance(properties, Mapping):
        return None
    subschema = cast(Mapping[str, object], properties).get(name)
    if isinstance(subschema, bool):
        return subschema
    if isinstance(subschema, Mapping):
        return cast(Mapping[str, object], subschema)
    return None


def evaluate_property(
    value: object, *, schema: Mapping[str, object], name: str, subschema: Schema
) -> ContractFinding:
    """The first error of ``value`` against ``subschema``, the property
    ``name`` of ``schema`` (``property_schema``), evaluated as validating an
    object that holds the value under that name evaluates it: its
    references resolve within ``schema``. ContractNotEvaluable when it cannot
    be evaluated, None when the value fits. ``schema`` is one that
    ``check_metaschema`` accepted; this does not check it again."""
    try:
        with _panic_as_recursion():
            # A schema of this one property, run with the resolver of the
            # whole schema.
            one_property = build_schema_validator(schema).evolve(
                schema={"properties": {name: subschema}}
            )
            error = next(iter(one_property.iter_errors({name: value})), None)
    except CONTRACT_FAILURES:
        return ContractNotEvaluable()
    return None if error is None else _violation(error)
