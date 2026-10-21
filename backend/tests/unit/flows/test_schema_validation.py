import asyncio

import pytest

from eneo.flows.definition import (
    FlowDefinition,
    FlowDefinitionError,
    JsonOutput,
    LlmStep,
    validate_definition,
)
from eneo.flows.schema_validation import check_schema, validate_value


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "imaginary"},
        {"$ref": "https://example.com/schema"},
        {"$ref": "file:///etc/passwd"},
        {"$id": "https://example.com/schema", "type": "object"},
        {"$ref": "#/$defs/missing"},
        {"default": {"type": "string"}, "$ref": "#/default"},
        {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object"},
    ],
)
def test_unsafe_or_invalid_output_schema_is_refused_before_publication(schema):
    flow = FlowDefinition(
        steps=[
            LlmStep(
                key="extract",
                name="Extract",
                prompt="p",
                input="",
                output=JsonOutput(schema=schema),
            )
        ]
    )
    with pytest.raises(FlowDefinitionError, match="output.schema"):
        validate_definition(flow)


async def test_local_references_validate_without_network_access():
    schema = {"$defs": {"value": {"type": "integer"}}, "$ref": "#/$defs/value"}
    check_schema(schema)
    await validate_value(3, schema)
    with pytest.raises(ValueError):
        await validate_value("3", schema)


def test_unknown_provider_schema_dialect_is_refused():
    with pytest.raises(ValueError, match="unsupported"):
        check_schema({"$schema": "https://example.com/unknown-dialect"}, authored=False)


async def test_pathological_regex_is_killed_and_does_not_block_the_event_loop(
    monkeypatch,
):
    from eneo.flows import schema_validation

    monkeypatch.setattr(schema_validation, "CHECK_TIMEOUT_SECONDS", 0.5)
    ticks = []

    async def tick():
        await asyncio.sleep(0.05)
        ticks.append(True)

    with pytest.raises(ValueError, match="within its limit"):
        await asyncio.gather(
            validate_value("a" * 100 + "!", {"type": "string", "pattern": "^(a+)+$"}),
            tick(),
        )
    assert ticks == [True]
    monkeypatch.setattr(schema_validation, "CHECK_TIMEOUT_SECONDS", 3)
    await validate_value(1, {"type": "integer"})


async def test_queue_wait_counts_towards_the_validation_deadline(monkeypatch):
    from eneo.flows import schema_validation

    slots = asyncio.Semaphore(1)
    await slots.acquire()
    monkeypatch.setattr(schema_validation, "_slots", slots)
    monkeypatch.setattr(schema_validation, "CHECK_TIMEOUT_SECONDS", 0.02)
    with pytest.raises(ValueError, match="within its limit"):
        await validate_value(1, {"type": "integer"})
    slots.release()
