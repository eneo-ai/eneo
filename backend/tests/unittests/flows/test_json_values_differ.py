from __future__ import annotations

import pytest

from eneo.flows.domain.canonical_json_hash import json_values_differ


@pytest.mark.parametrize(
    ("stored", "incoming"),
    [
        ({"n": 1}, {"n": True}),
        ({"f": 1.0}, {"f": 1}),
        ({"a": {"b": [1, {"c": True}]}}, {"a": {"b": [1, {"c": 1}]}}),
        ({"k": "åäö"}, {"k": "åäo"}),
        (None, {}),
        ({}, None),
        ([1, 2], [2, 1]),
        ({"a": 1}, [1]),
    ],
)
def test_json_that_differs_in_type_or_content_differs(
    stored: object, incoming: object
) -> None:
    assert json_values_differ(stored, incoming)


@pytest.mark.parametrize(
    ("stored", "incoming"),
    [
        ({"a": 1, "b": 2}, {"b": 2, "a": 1}),
        ({"k": "åäö", "n": {"x": 1.5}}, {"n": {"x": 1.5}, "k": "åäö"}),
        ({"a": {"c": [1, {"e": 1, "d": 2}]}}, {"a": {"c": [1, {"d": 2, "e": 1}]}}),
        (None, None),
        (3, 3),
        ("x", "x"),
    ],
)
def test_json_that_is_the_same_value_is_not_a_difference(
    stored: object, incoming: object
) -> None:
    assert not json_values_differ(stored, incoming)


def test_a_scalar_is_compared_as_python_compares_it() -> None:
    assert json_values_differ(1, 2)
    assert not json_values_differ(1, 1)
