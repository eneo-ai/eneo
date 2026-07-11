from __future__ import annotations

from dataclasses import fields
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import eneo.flows.published_definition as published_definition_module
from eneo.flows.assistant_execution_snapshot import stable_hash
from eneo.flows.domain.runtime_invariant_exceptions import (
    FlowPublishedDefinitionWithoutExecutableStepsError,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_metadata import FlowFormFieldType, serialize_flow_metadata
from eneo.flows.flow_review_policy import (
    FLOW_REVIEW_POLICY_INVALID,
    FLOW_REVIEW_POLICY_OUTBOUND_OUTPUT_UNSUPPORTED,
    FlowStepReviewMode,
)
from eneo.flows.published_definition import (
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
from eneo.main.exceptions import BadRequestException


def _step(*, order: object = 1):
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
    step_id = uuid4()
    assistant_id = uuid4()
    definition = build_published_definition_json(
        flow_id=flow_id,
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[
            {
                **_step(order=1),
                "step_id": str(step_id),
                "assistant_id": str(assistant_id),
            }
        ],
    )

    parsed = parse_published_definition(definition, flow_version=7)
    runtime_steps = parse_published_runtime_steps(definition, flow_version=7)

    assert parsed.schema_version == FLOW_DEFINITION_SCHEMA_VERSION
    assert parsed.flow_id == flow_id
    assert parsed.name == "Flow"
    assert parsed.steps == definition["steps"]
    assert len(parsed.step_identities) == 1
    step_identity = parsed.step_identities[0]
    assert step_identity.step_id == step_id
    assert step_identity.step_order == 1
    assert step_identity.assistant_id == assistant_id
    assert len(runtime_steps) == 1
    assert runtime_steps[0].step_order == 1


@pytest.mark.parametrize(
    ("step_snapshot", "error_code", "error_context"),
    [
        (
            {"step_order": 1, "assistant_id": str(uuid4())},
            "flow_version_missing_step_identifiers",
            {"step_order": 1},
        ),
        (
            {"step_order": 1, "step_id": str(uuid4()), "assistant_id": None},
            "flow_version_missing_step_identifiers",
            {"step_order": 1},
        ),
        (
            {"step_order": 1, "step_id": "not-a-uuid", "assistant_id": str(uuid4())},
            "flow_version_invalid_step_identifier",
            {"step_order": 1, "field": "step_id", "value": "not-a-uuid"},
        ),
        (
            {"step_order": 1, "step_id": str(uuid4()), "assistant_id": "bad-id"},
            "flow_version_invalid_step_identifier",
            {"step_order": 1, "field": "assistant_id", "value": "bad-id"},
        ),
        (
            {"step_order": True, "step_id": str(uuid4()), "assistant_id": str(uuid4())},
            "flow_version_invalid_step_order",
            {"step_order": True},
        ),
        (
            {
                "step_order": "abc",
                "step_id": str(uuid4()),
                "assistant_id": str(uuid4()),
            },
            "flow_version_invalid_step_order",
            {"step_order": "abc"},
        ),
        (
            {"step_order": 1.5, "step_id": str(uuid4()), "assistant_id": str(uuid4())},
            "flow_version_invalid_step_order",
            {"step_order": 1.5},
        ),
        (
            {"step_order": 0, "step_id": str(uuid4()), "assistant_id": str(uuid4())},
            "flow_version_invalid_step_order",
            {"step_order": 0},
        ),
        (
            {"step_order": -1, "step_id": str(uuid4()), "assistant_id": str(uuid4())},
            "flow_version_invalid_step_order",
            {"step_order": -1},
        ),
    ],
)
def test_published_definition_validates_step_identity_at_construction(
    step_snapshot: dict[str, object],
    error_code: str,
    error_context: dict[str, object],
) -> None:
    definition = build_published_definition_json(
        flow_id=uuid4(),
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[step_snapshot],
    )

    with pytest.raises(BadRequestException) as exc_info:
        parse_published_definition(definition, flow_version=7)

    assert exc_info.value.code == error_code
    assert exc_info.value.context == error_context


def test_parser_rejects_definition_without_executable_steps() -> None:
    flow_id = uuid4()
    definition = build_published_definition_json(
        flow_id=flow_id,
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[],
    )

    with pytest.raises(FlowPublishedDefinitionWithoutExecutableStepsError) as exc_info:
        parse_published_definition(definition, flow_version=7)

    assert exc_info.value.flow_id == flow_id
    assert exc_info.value.flow_version == 7


def test_runtime_steps_rejects_definition_without_executable_steps() -> None:
    flow_id = uuid4()
    definition = build_published_definition_json(
        flow_id=flow_id,
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[],
    )

    with pytest.raises(FlowPublishedDefinitionWithoutExecutableStepsError) as exc_info:
        parse_published_runtime_steps(definition, flow_version=9)

    assert exc_info.value.flow_id == flow_id
    assert exc_info.value.flow_version == 9


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
            "wizard": {"transcription_enabled": True},
        },
        steps=[_step(order=1)],
    )

    parsed = parse_published_definition(definition, flow_version=7)
    metadata = parsed.metadata()

    assert "metadata_json" not in {field.name for field in fields(parsed)}
    assert metadata.form_schema is not None
    assert metadata.form_schema.fields[0].name == "case_id"
    assert metadata.form_schema.fields[0].type is FlowFormFieldType.TEXT
    assert metadata.care_data_policy.sensitive is True
    assert serialize_flow_metadata(metadata) == {
        "form_schema": {
            "fields": [
                {
                    "name": "case_id",
                    "type": "text",
                    "label": "Case",
                    "required": True,
                    "order": 2,
                }
            ]
        },
        "care_data_policy": {"sensitive": True},
        "wizard": {"transcription_enabled": True},
    }


@pytest.mark.parametrize(
    ("metadata_json", "expected_context"),
    [
        ({"form_schema": {"fields": "not-a-list"}}, None),
        (
            {"form_schema": {"fields": [{"name": "case_id", "type": "unsupported"}]}},
            None,
        ),
        (
            {
                "form_schema": {
                    "fields": [{"name": "case_id", "type": "text", "label": 7}]
                }
            },
            None,
        ),
        ({"form_schema": {"fields": [{"type": "text"}]}}, {"field_index": 0}),
    ],
)
def test_metadata_maps_corrupt_published_form_schema_to_named_error(
    metadata_json: dict[str, object],
    expected_context: dict[str, object] | None,
) -> None:
    definition = build_published_definition_json(
        flow_id=uuid4(),
        name="Flow",
        description=None,
        metadata_json=metadata_json,
        steps=[_step(order=1)],
    )

    with pytest.raises(BadRequestException) as exc_info:
        parse_published_definition(definition, flow_version=7).metadata()

    assert exc_info.value.code == FLOW_PUBLISHED_FORM_SCHEMA_INVALID
    assert exc_info.value.context == expected_context


def test_parser_round_trips_step_review_policy() -> None:
    definition = build_published_definition_json(
        flow_id=uuid4(),
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[{**_step(order=1), "review_policy": {"mode": "edit"}}],
    )

    runtime_steps = parse_published_runtime_steps(definition, flow_version=7)

    assert runtime_steps[0].review_policy is not None
    assert runtime_steps[0].review_policy.mode == FlowStepReviewMode.EDIT


def test_parser_accepts_published_review_policy_with_explicit_null_expiry() -> None:
    definition = build_published_definition_json(
        flow_id=uuid4(),
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[
            {
                **_step(order=1),
                "review_policy": {"mode": "view", "expires_after_seconds": None},
            }
        ],
    )

    runtime_steps = parse_published_runtime_steps(definition, flow_version=7)

    assert runtime_steps[0].review_policy is not None
    assert runtime_steps[0].review_policy.expires_after_seconds is None


def test_parser_reports_invalid_review_policy_with_step_context() -> None:
    definition = build_published_definition_json(
        flow_id=uuid4(),
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[
            {
                **_step(order=1),
                "user_description": "Draft review",
                "review_policy": {"mode": "approve"},
            }
        ],
    )

    with pytest.raises(BadRequestException) as exc_info:
        parse_published_runtime_steps(definition, flow_version=7)

    assert exc_info.value.code == FLOW_REVIEW_POLICY_INVALID
    assert str(exc_info.value).startswith("Step 1 (Draft review):")
    assert exc_info.value.context == {
        "step_order": 1,
        "step_description": "Draft review",
    }


def test_parser_reports_other_step_errors_with_step_context() -> None:
    definition = build_published_definition_json(
        flow_id=uuid4(),
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[
            {
                **_step(order=1),
                "user_description": "Invalid mode",
                "output_mode": "unsupported",
            }
        ],
    )

    with pytest.raises(BadRequestException) as exc_info:
        parse_published_runtime_steps(definition, flow_version=7)

    assert (
        str(exc_info.value)
        == "Step 1 (Invalid mode): Unsupported output mode 'unsupported'."
    )
    assert exc_info.value.context == {
        "step_order": 1,
        "step_description": "Invalid mode",
    }


@pytest.mark.parametrize(
    ("input_config", "expected"),
    [
        ({"runtime_input": {"enabled": True, "required": True}}, True),
        ({"runtime_input": {"enabled": True, "required": False}}, False),
        ({"runtime_input": {"enabled": False, "required": True}}, False),
        ({}, False),
        (None, False),
    ],
)
def test_published_definition_detects_required_runtime_input(
    input_config: dict[str, object] | None,
    expected: bool,
) -> None:
    definition = build_published_definition_json(
        flow_id=uuid4(),
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[{**_step(order=1), "input_config": input_config}],
    )

    published_definition = parse_published_definition(definition, flow_version=7)

    assert published_definition.has_required_runtime_input() is expected


def test_published_definition_rejects_non_object_input_config() -> None:
    definition = build_published_definition_json(
        flow_id=uuid4(),
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[{**_step(order=1), "input_config": "not-an-object"}],
    )
    with pytest.raises(BadRequestException) as exc_info:
        parse_published_definition(definition, flow_version=7)

    assert exc_info.value.code == FLOW_DEFINITION_STEPS_INVALID
    assert str(exc_info.value) == "Step 1: input_config must be an object."


def test_published_definition_detects_required_runtime_input_after_optional_step() -> (
    None
):
    definition = build_published_definition_json(
        flow_id=uuid4(),
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[
            {
                **_step(order=1),
                "input_config": {"runtime_input": {"enabled": True}},
            },
            {
                **_step(order=2),
                "input_source": "previous_step",
                "input_config": {"runtime_input": {"enabled": True, "required": True}},
            },
        ],
    )
    published_definition = parse_published_definition(definition, flow_version=7)

    assert published_definition.has_required_runtime_input()


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
        parse_published_runtime_steps(definition, flow_version=7)

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
        parse_published_runtime_steps(definition, flow_version=7)

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


def test_verified_parser_rejects_checksum_mismatch_with_typed_context() -> None:
    definition = build_published_definition_json(
        flow_id=uuid4(),
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[_step(order=1)],
    )
    expected_checksum = stable_hash({"different": "snapshot"})

    with pytest.raises(FlowBadRequestException) as exc_info:
        published_definition_module.parse_verified_published_definition(
            definition,
            expected_checksum=expected_checksum,
            flow_version=7,
        )

    assert exc_info.value.code is FlowApiErrorCode.DEFINITION_CHECKSUM_MISMATCH
    assert exc_info.value.context == {
        "expected_checksum": expected_checksum,
        "current_checksum": published_definition_checksum(definition),
    }


def test_verified_parser_rejects_matching_checksum_invalid_runtime_step() -> None:
    invalid_step = _step(order=1)
    invalid_step["output_mode"] = "invalid_mode"
    definition = build_published_definition_json(
        flow_id=uuid4(),
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[invalid_step],
    )

    integrity = published_definition_module.inspect_published_definition_integrity(
        definition,
        expected_checksum=published_definition_checksum(definition),
        flow_version=7,
    )

    assert (
        integrity.status
        is published_definition_module.PublishedDefinitionIntegrityStatus.INVALID
    )

    with pytest.raises(BadRequestException) as exc_info:
        published_definition_module.parse_verified_published_definition(
            definition,
            expected_checksum=published_definition_checksum(definition),
            flow_version=7,
        )

    assert exc_info.value.code == FLOW_DEFINITION_STEPS_INVALID


def test_verified_parser_reuses_one_full_validation_result(monkeypatch) -> None:
    definition = build_published_definition_json(
        flow_id=uuid4(),
        name="Flow",
        description=None,
        metadata_json=None,
        steps=[
            {
                **_step(order=1),
                "input_config": {"runtime_input": {"enabled": True, "required": True}},
            }
        ],
    )
    checksum_spy = MagicMock(
        wraps=published_definition_module.published_definition_checksum
    )
    metadata_spy = MagicMock(wraps=published_definition_module.parse_flow_metadata)
    runtime_steps_spy = MagicMock(wraps=published_definition_module.parse_runtime_steps)
    monkeypatch.setattr(
        published_definition_module,
        "published_definition_checksum",
        checksum_spy,
    )
    monkeypatch.setattr(
        published_definition_module,
        "parse_flow_metadata",
        metadata_spy,
    )
    monkeypatch.setattr(
        published_definition_module,
        "parse_runtime_steps",
        runtime_steps_spy,
    )

    parsed = published_definition_module.parse_verified_published_definition(
        definition,
        expected_checksum=published_definition_checksum(definition),
        flow_version=7,
    )
    first_metadata = parsed.metadata()
    second_metadata = parsed.metadata()
    first_steps = parsed.runtime_steps()
    second_steps = parsed.runtime_steps()

    assert first_metadata == second_metadata
    assert first_metadata is not second_metadata
    assert first_steps == second_steps
    assert first_steps is not second_steps
    assert parsed.has_required_runtime_input() is True
    assert checksum_spy.call_count == 1
    assert metadata_spy.call_count == 1
    assert runtime_steps_spy.call_count == 1
