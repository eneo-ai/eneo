from __future__ import annotations

from dataclasses import fields
from uuid import uuid4

import pytest

from intric.flows.assistant_execution_snapshot import stable_hash
from intric.flows.flow_metadata import FlowFormFieldType, serialize_flow_metadata
from intric.flows.flow_review_policy import (
    FLOW_REVIEW_POLICY_OUTBOUND_OUTPUT_UNSUPPORTED,
    FlowStepReviewMode,
)
from intric.flows.published_definition import (
    FLOW_DEFINITION_FLOW_ID_INVALID,
    FLOW_DEFINITION_SCHEMA_VERSION,
    FLOW_DEFINITION_SCHEMA_VERSION_MISSING,
    FLOW_DEFINITION_SCHEMA_VERSION_UNSUPPORTED,
    FLOW_DEFINITION_STEPS_INVALID,
    FLOW_PUBLISHED_FORM_SCHEMA_INVALID,
    build_published_definition_json,
    parse_published_definition,
    parse_published_runtime_steps,
    published_definition_checksum,
)
from intric.main.exceptions import BadRequestException


def _step(*, order: int = 1):
    return {
        "step_id": str(uuid4()),
        "step_order": order,
        "assistant_id": str(uuid4()),
        "input_source": "flow_input",
        "input_type": "text",
        "output_type": "text",
        "output_mode": "pass_through",
    }


def test_writer_owns_definition_envelope_and_orders_steps() -> None:
    flow_id = uuid4()
    second = _step(order=2)
    first = _step(order=1)

    definition = build_published_definition_json(
        flow_id=flow_id,
        name="Flow",
        description="Description",
        metadata_json={"form_schema": []},
        steps=[second, first],
    )

    assert definition["schema_version"] == FLOW_DEFINITION_SCHEMA_VERSION
    assert definition["flow_id"] == str(flow_id)
    assert definition["name"] == "Flow"
    assert definition["description"] == "Description"
    assert definition["metadata_json"] == {"form_schema": []}
    assert [step["step_order"] for step in definition["steps"]] == [1, 2]


def test_parser_round_trips_definition_and_runtime_steps() -> None:
    flow_id = uuid4()
    definition = build_published_definition_json(
        flow_id=flow_id,
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[_step(order=1)],
    )

    parsed = parse_published_definition(definition)
    runtime_steps = parse_published_runtime_steps(definition)

    assert parsed.schema_version == FLOW_DEFINITION_SCHEMA_VERSION
    assert parsed.flow_id == flow_id
    assert parsed.name == "Flow"
    assert parsed.steps == definition["steps"]
    assert len(runtime_steps) == 1
    assert runtime_steps[0].step_order == 1


def test_parser_exposes_typed_metadata_without_raw_metadata_field() -> None:
    definition = build_published_definition_json(
        flow_id=uuid4(),
        name="Flow",
        description=None,
        metadata_json={
            "form_schema": {
                "fields": [
                    {
                        "name": "case_id",
                        "type": "email",
                        "label": "Case",
                        "required": True,
                        "order": 2,
                    }
                ]
            },
            "care_data_policy": {"sensitive": True},
            "external_owner": "case-system",
        },
        steps=[_step(order=1)],
    )

    parsed = parse_published_definition(definition)
    metadata = parsed.metadata()

    assert "metadata_json" not in {field.name for field in fields(parsed)}
    assert metadata.form_schema is not None
    assert metadata.form_schema.fields[0].name == "case_id"
    assert metadata.form_schema.fields[0].type is FlowFormFieldType.TEXT
    assert metadata.care_data_policy.sensitive is True
    assert serialize_flow_metadata(metadata)["external_owner"] == "case-system"


@pytest.mark.parametrize(
    "metadata_json",
    [
        {"form_schema": {"fields": "not-a-list"}},
        {"form_schema": {"fields": [{"name": "case_id", "type": "unsupported"}]}},
        {"form_schema": {"fields": [{"type": "text"}]}},
    ],
)
def test_metadata_maps_corrupt_published_form_schema_to_named_error(
    metadata_json: dict[str, object],
) -> None:
    definition = build_published_definition_json(
        flow_id=uuid4(),
        name="Flow",
        description=None,
        metadata_json=metadata_json,
        steps=[_step(order=1)],
    )

    with pytest.raises(BadRequestException) as exc_info:
        parse_published_definition(definition).metadata()

    assert exc_info.value.code == FLOW_PUBLISHED_FORM_SCHEMA_INVALID


def test_parser_round_trips_step_review_policy() -> None:
    definition = build_published_definition_json(
        flow_id=uuid4(),
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[{**_step(order=1), "review_policy": {"mode": "edit"}}],
    )

    runtime_steps = parse_published_runtime_steps(definition)

    assert runtime_steps[0].review_policy is not None
    assert runtime_steps[0].review_policy.mode == FlowStepReviewMode.EDIT


def test_parser_rejects_review_policy_for_outbound_delivery() -> None:
    definition = build_published_definition_json(
        flow_id=uuid4(),
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[
            {
                **_step(order=1),
                "output_mode": "http_post",
                "output_config": {"url": "https://example.test/hook"},
                "review_policy": {"mode": "view"},
            }
        ],
    )

    with pytest.raises(BadRequestException) as exc_info:
        parse_published_runtime_steps(definition)

    assert exc_info.value.code == FLOW_REVIEW_POLICY_OUTBOUND_OUTPUT_UNSUPPORTED


@pytest.mark.parametrize(
    ("definition", "error_code"),
    [
        ({"steps": []}, FLOW_DEFINITION_SCHEMA_VERSION_MISSING),
        (
            {"schema_version": 999, "flow_id": str(uuid4()), "steps": []},
            FLOW_DEFINITION_SCHEMA_VERSION_UNSUPPORTED,
        ),
        (
            {
                "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
                "flow_id": str(uuid4()),
            },
            FLOW_DEFINITION_STEPS_INVALID,
        ),
        (
            {
                "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
                "flow_id": "not-a-uuid",
                "steps": [],
            },
            FLOW_DEFINITION_FLOW_ID_INVALID,
        ),
        (
            {
                "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
                "flow_id": str(uuid4()),
                "steps": ["not-a-step"],
            },
            FLOW_DEFINITION_STEPS_INVALID,
        ),
    ],
)
def test_parser_rejects_corrupt_definition_with_named_error(
    definition, error_code: str
) -> None:
    with pytest.raises(BadRequestException) as exc_info:
        parse_published_runtime_steps(definition)

    assert exc_info.value.code == error_code


def test_checksum_uses_stable_hash_contract() -> None:
    definition = build_published_definition_json(
        flow_id=uuid4(),
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[_step(order=1)],
    )

    assert published_definition_checksum(definition) == stable_hash(definition)
