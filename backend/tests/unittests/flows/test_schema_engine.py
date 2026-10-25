"""The metaschema check remembers which schemas it accepted, by their content,
and answers every schema as the check itself does."""

from __future__ import annotations

from collections import OrderedDict

import jsonschema
import pytest

from eneo.flows.domain import schema_engine
from eneo.flows.domain.schema_engine import check_metaschema
from eneo.flows.output_processing import validate_schema_syntax
from eneo.main.exceptions import TypedIOValidationException

_DRAFT = jsonschema.Draft202012Validator


@pytest.fixture
def metaschema_checks(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """An empty verdict cache, and every schema the metaschema check reads."""
    monkeypatch.setattr(schema_engine, "_metaschema_verdicts", OrderedDict())
    checked: list[object] = []
    build = schema_engine.build_schema_validator

    class Counting:
        def __init__(self, validator: schema_engine.SchemaValidator) -> None:
            self._validator = validator

        def validate(self, instance: object) -> None:
            checked.append(instance)
            self._validator.validate(instance)

    def counting_build(schema, **kwargs):
        validator = build(schema, **kwargs)
        return Counting(validator) if schema is _DRAFT.META_SCHEMA else validator

    monkeypatch.setattr(schema_engine, "build_schema_validator", counting_build)
    return checked


def _contract(properties: int) -> dict[str, object]:
    names = [f"f{index}" for index in range(properties)]
    return {
        "type": "object",
        "properties": {name: {"type": "string"} for name in names},
        "required": names,
    }


def test_a_schema_with_the_content_of_an_accepted_one_is_not_checked_again(
    metaschema_checks: list[object],
) -> None:
    check_metaschema(_contract(20), _DRAFT)
    check_metaschema(_contract(20), _DRAFT)
    validate_schema_syntax(_contract(20), label="Step 2 output_contract")

    assert len(metaschema_checks) == 1


def test_a_refused_schema_is_refused_with_the_same_message_every_time(
    metaschema_checks: list[object],
) -> None:
    schema = {"type": "object", "properties": {"a": {"type": "not_a_type"}}}

    messages = []
    for _ in range(3):
        with pytest.raises(TypedIOValidationException) as refused:
            validate_schema_syntax(schema, label="Step 2 output_contract")
        assert refused.value.code == "typed_io_invalid_schema"
        messages.append(str(refused.value))

    assert (
        messages
        == [
            "Step 2 output_contract is not a valid JSON Schema: 'not_a_type' is not "
            "valid under any of the given schemas"
        ]
        * 3
    )
    # A refusal's message holds part of the schema; it is never remembered.
    assert len(metaschema_checks) == 3
    assert not schema_engine._metaschema_verdicts


def test_a_verdict_is_the_dialects_it_was_given(
    metaschema_checks: list[object],
) -> None:
    # The array form of `items` is draft 7's and no 2020-12 schema.
    schema = {"type": "array", "items": [{"type": "string"}]}

    check_metaschema(schema, jsonschema.Draft7Validator)
    with pytest.raises(jsonschema.SchemaError):
        check_metaschema(schema, _DRAFT)


def test_the_verdicts_kept_are_bounded_and_the_least_recently_used_goes_first(
    metaschema_checks: list[object],
) -> None:
    size = schema_engine.METASCHEMA_VERDICTS_MAX
    for length in range(size):
        check_metaschema({"maxLength": length}, _DRAFT)
    check_metaschema({"maxLength": 0}, _DRAFT)  # used again, so kept
    check_metaschema({"maxLength": size}, _DRAFT)  # evicts maxLength 1

    assert len(schema_engine._metaschema_verdicts) == size
    del metaschema_checks[:]
    check_metaschema({"maxLength": 0}, _DRAFT)
    assert metaschema_checks == []
    check_metaschema({"maxLength": 1}, _DRAFT)
    assert metaschema_checks == [{"maxLength": 1}]


def test_a_schema_the_check_cannot_finish_is_checked_every_time(
    metaschema_checks: list[object],
) -> None:
    schema: dict[str, object] = {"type": "object"}
    schema["properties"] = {"self": schema}

    for _ in range(2):
        with pytest.raises(RecursionError):
            check_metaschema(schema, _DRAFT)
    assert len(metaschema_checks) == 2
    assert not schema_engine._metaschema_verdicts
