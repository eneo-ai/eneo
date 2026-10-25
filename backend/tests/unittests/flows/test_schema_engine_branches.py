"""anyOf and oneOf read a failing branch only up to its first error, and
answer every value as jsonschema's own validator of the same draft does."""

from __future__ import annotations

import tracemalloc
from collections.abc import Callable, Iterator
from typing import Any

import jsonschema
import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from jsonschema.protocols import Validator

from eneo.flows.domain import schema_engine
from eneo.flows.domain.schema_engine import (
    ContractViolation,
    build_schema_validator,
    evaluate_contract,
)

_DIALECTS = (
    jsonschema.Draft6Validator,
    jsonschema.Draft7Validator,
    jsonschema.Draft201909Validator,
    jsonschema.Draft202012Validator,
)
_2020_12 = "https://json-schema.org/draft/2020-12/schema"
_DRAFT_07 = "http://json-schema.org/draft-07/schema#"
_MiB = 1024 * 1024

_NAMES = st.sampled_from("abc")
_INSTANCES = st.recursive(
    st.none() | st.booleans() | st.integers(-3, 3) | st.sampled_from(["", "a", "abcd"]),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(_NAMES, children, max_size=3)
    ),
    max_leaves=10,
)
_LEAVES = st.one_of(
    st.booleans(),
    st.just({}),
    st.builds(
        lambda name: {"type": name},
        st.sampled_from(["null", "boolean", "integer", "string", "array", "object"]),
    ),
    st.builds(lambda bound: {"minimum": bound}, st.integers(-2, 2)),
    st.builds(lambda bound: {"maxLength": bound}, st.integers(0, 2)),
    st.builds(lambda bound: {"minItems": bound}, st.integers(0, 2)),
    st.builds(lambda value: {"const": value}, _INSTANCES),
    st.builds(
        lambda names: {"required": names},
        st.lists(_NAMES, min_size=1, max_size=2, unique=True),
    ),
)


def _applicators(children: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    branches = st.lists(children, min_size=1, max_size=4)
    objects = children.filter(lambda schema: isinstance(schema, dict))
    return st.one_of(
        st.builds(lambda each: {"anyOf": each}, branches),
        st.builds(lambda each: {"oneOf": each}, branches),
        st.builds(lambda each: {"allOf": each}, branches),
        st.builds(lambda schema: {"not": schema}, children),
        st.builds(
            lambda if_, then, else_: {"if": if_, "then": then, "else": else_},
            children,
            children,
            children,
        ),
        st.builds(lambda schema: {"items": schema}, children),
        st.builds(
            lambda each: {"properties": each},
            st.dictionaries(_NAMES, children, max_size=3),
        ),
        # Several keywords in one schema, so that a branch fails more than once.
        st.builds(lambda first, second: {**first, **second}, objects, objects),
    )


_SCHEMAS = st.recursive(_LEAVES, _applicators, max_leaves=12)

_Context = Callable[[jsonschema.ValidationError], list[jsonschema.ValidationError]]


def _shape(error: jsonschema.ValidationError, context: _Context) -> tuple[object, ...]:
    return (
        error.validator,
        list(error.absolute_path),
        list(error.absolute_schema_path),
        error.message,
        [_shape(each, context) for each in context(error)],
    )


def _whole_context(
    error: jsonschema.ValidationError,
) -> list[jsonschema.ValidationError]:
    return list(error.context)


def _first_of_each_branch(
    error: jsonschema.ValidationError,
) -> list[jsonschema.ValidationError]:
    first: dict[object, jsonschema.ValidationError] = {}
    for position, each in enumerate(error.context):
        # jsonschema gives the one error of a false branch no schema path.
        path = each.relative_schema_path
        first.setdefault(path[0] if path else ("false", position), each)
    return list(first.values())


def _within(error: jsonschema.ValidationError) -> Iterator[jsonschema.ValidationError]:
    yield error
    for each in error.context:
        yield from _within(each)


def _assert_answers_as_its_draft(schema: Any, instance: object) -> None:
    """Our validator gives the verdict and every error (keyword, path, schema
    path, message) of the stock validator of the schema's draft, and as
    context the first error of each failing branch."""
    ours = build_schema_validator(schema)
    stock = schema_engine.dialect_of(schema)(
        schema, registry=schema_engine.LOCAL_SCHEMA_REGISTRY
    )

    assert (next(ours.iter_errors(instance), None) is None) == stock.is_valid(instance)
    assert [_shape(error, _whole_context) for error in ours.iter_errors(instance)] == [
        _shape(error, _first_of_each_branch) for error in stock.iter_errors(instance)
    ]


@given(dialect=st.sampled_from(_DIALECTS), schema=_SCHEMAS, instance=_INSTANCES)
@example(
    dialect=jsonschema.Draft202012Validator,
    schema={"anyOf": [{"items": {"type": "string"}}, {"minItems": 3, "maxItems": 0}]},
    instance=[1, 2],
)
def test_every_value_is_answered_as_by_the_drafts_own_validator(
    dialect: type[Validator], schema: Any, instance: object
) -> None:
    # Kills a branch that stops before its first error or reads on past it,
    # a verdict or error other than the draft's own, and a context holding
    # more than each failing branch's first error.
    _assert_answers_as_its_draft(
        {"$schema": dialect.META_SCHEMA["$schema"], "allOf": [schema]}, instance
    )


@pytest.mark.parametrize(
    "schema",
    [
        # A reference to a schema that names its dialect.
        {
            "$schema": _2020_12,
            "items": {"$ref": "#/$defs/strings"},
            "$defs": {
                "strings": {
                    "$schema": _2020_12,
                    "anyOf": [
                        {"items": {"type": "string"}},
                        {"items": {"type": "boolean"}},
                    ],
                }
            },
        },
        # A reference to the root, which names its dialect.
        {
            "$schema": _2020_12,
            "anyOf": [{"type": "string"}, {"type": "array", "items": {"$ref": "#"}}],
        },
        # A subschema of another draft, read by that draft's rules: draft 7
        # reads the array form of items as one schema per position.
        {
            "$schema": _2020_12,
            "items": {
                "$schema": _DRAFT_07,
                "oneOf": [
                    {"items": [{"type": "string"}, {"type": "string"}]},
                    {"items": {"type": "boolean"}},
                ],
            },
        },
    ],
)
def test_a_subschema_that_names_its_dialect_keeps_first_errors(schema) -> None:
    # Kills a validator that, entering a schema with $schema, goes back to
    # the stock class (and keeps every error of each branch below), or loses
    # that schema's draft.
    instance = [[1, 2, 3]]

    _assert_answers_as_its_draft(schema, instance)
    error = next(build_schema_validator(schema).iter_errors(instance))
    assert error.validator in {"anyOf", "oneOf"}
    assert all(len(each.context) <= 2 for each in _within(error))


def test_one_of_with_two_valid_branches_is_valid_under_each() -> None:
    # Kills a oneOf that stops at its first valid branch.
    schema = {"oneOf": [{"type": "string"}, {"type": "integer"}, {"minimum": 0}]}

    _assert_answers_as_its_draft(schema, 5)
    error = next(build_schema_validator(schema).iter_errors(5))
    assert error.message == (
        "5 is valid under each of {'minimum': 0}, {'type': 'integer'}"
    )
    assert evaluate_contract(5, schema) == ContractViolation(
        path=(), rule="oneOf", detail="Value does not satisfy schema rule 'oneOf'."
    )


def _branches(keyword: str, failing: int) -> dict[str, object]:
    strings: list[object] = [{"items": {"type": "string"}} for _ in range(failing)]
    return {"type": "array", keyword: [*strings, {"items": {"type": "integer"}}]}


@pytest.mark.parametrize(
    ("schema", "items"),
    [
        (_branches("oneOf", 1), 200_000),
        (_branches("anyOf", 1), 200_000),
        (_branches("anyOf", 15), 20_000),
    ],
    ids=["oneOf2", "anyOf2", "anyOf16"],
)
def test_a_valid_value_does_not_keep_the_failing_branches_errors(schema, items) -> None:
    # Kills a failing branch that keeps an error per item: stock jsonschema
    # peaks at 555-830 MiB on these, past the argument check's memory budget.
    value = list(range(items))
    evaluate_contract([], schema)  # the metaschema verdict, outside the peak

    tracemalloc.start()
    try:
        finding = evaluate_contract(value, schema)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert finding is None
    assert peak < 8 * _MiB
