"""The JSON Schema engine every Flow check of data against a schema uses.

It imports jsonschema and referencing and nothing of Eneo, so that the child
process that checks a tool step's arguments (runtime/tool_argument_check.py)
does not import what output_processing imports.
"""

from __future__ import annotations

import re
from collections.abc import Generator, Iterator
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
# or unhashable `type` or `$schema`, and an expression `re` cannot compile.
CONTRACT_FAILURES = (
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


def check_metaschema(schema: Schema, dialect: type[Validator]) -> None:
    validator = build_schema_validator(
        dialect.META_SCHEMA, format_checker=dialect.FORMAT_CHECKER
    )
    try:
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


def evaluate_contract(data: object, schema: Schema) -> ContractFinding:
    """The first error of ``data`` against ``schema``, ContractNotEvaluable
    when the schema is not a valid schema of the draft it names or cannot be
    evaluated against ``data``, None when ``data`` fits."""
    try:
        check_metaschema(schema, dialect_of(schema))
        with _panic_as_recursion():
            build_schema_validator(schema).validate(data)
    except jsonschema.ValidationError as exc:
        rule = exc.validator if isinstance(exc.validator, str) else None
        if rule == "type":
            detail = f"Value is not of type {exc.validator_value!r}."
        elif rule == "required":
            detail = exc.message
        elif rule == "additionalProperties":
            detail = "Additional properties are not allowed."
        else:
            detail = f"Value does not satisfy schema rule '{rule}'."
        return ContractViolation(
            path=tuple(exc.absolute_path), rule=rule, detail=detail
        )
    except CONTRACT_FAILURES:
        return ContractNotEvaluable()
    return None
