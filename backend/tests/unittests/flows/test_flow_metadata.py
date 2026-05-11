from __future__ import annotations

import re

import pytest

from intric.flows.flow_metadata import (
    FlowCareDataPolicyV1,
    FlowFormFieldType,
    FlowFormSchemaParseMode,
    FlowMetadataParseMode,
    parse_flow_form_schema,
    parse_flow_metadata,
    serialize_flow_form_schema,
    serialize_flow_metadata,
)
from intric.main.exceptions import BadRequestException


def _metadata(fields: list[dict[str, object]]) -> dict[str, object]:
    return {"form_schema": {"fields": fields}}


@pytest.mark.parametrize(
    ("metadata_json", "message"),
    [
        ({"form_schema": []}, "metadata_json.form_schema must be an object."),
        (
            {"form_schema": {"fields": "not-a-list"}},
            "metadata_json.form_schema.fields must be a list.",
        ),
        (
            {"form_schema": {"fields": ["not-an-object"]}},
            "metadata_json.form_schema.fields[0] must be an object.",
        ),
        (
            _metadata([{"name": "", "type": "text"}]),
            "Form field 1 needs a name before the flow can be saved.",
        ),
        (
            _metadata([{"name": "case.id", "type": "text"}]),
            "Field names cannot contain dots",
        ),
        (
            _metadata([{"name": "case_id", "type": ""}]),
            "metadata_json.form_schema.fields[0].type must be a non-empty string.",
        ),
        (
            _metadata([{"name": "case_id", "type": "file"}]),
            "metadata_json.form_schema.fields[0].type must be one of",
        ),
        (
            _metadata([{"name": "case_id", "type": "text", "required": "yes"}]),
            "metadata_json.form_schema.fields[0].required must be a boolean.",
        ),
        (
            _metadata([{"name": "case_id", "type": "text", "order": "1"}]),
            "metadata_json.form_schema.fields[0].order must be an integer.",
        ),
        (
            _metadata([{"name": "case_id", "type": "text", "order": 0}]),
            "metadata_json.form_schema.fields[0].order must be >= 1.",
        ),
        (
            _metadata([{"name": "case_id", "type": "multiselect"}]),
            "metadata_json.form_schema.fields[0].options must be a list for multiselect.",
        ),
        (
            _metadata([{"name": "case_id", "type": "select", "options": "a"}]),
            "metadata_json.form_schema.fields[0].options must be a list for select.",
        ),
        (
            _metadata([{"name": "case_id", "type": "select", "options": [""]}]),
            "metadata_json.form_schema.fields[0].options[0] must be a non-empty string.",
        ),
        (
            _metadata([{"name": "case_id", "type": "select", "options": ["a", "A"]}]),
            "metadata_json.form_schema.fields[0].options[1] must be unique.",
        ),
        (
            _metadata([{"name": "case_id", "type": "text", "options": ["a"]}]),
            "metadata_json.form_schema.fields[0].options is only valid for select or multiselect.",
        ),
    ],
)
def test_parse_flow_form_schema_preserves_write_error_messages(
    metadata_json: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(BadRequestException, match=re.escape(message)):
        parse_flow_form_schema(metadata_json, mode=FlowFormSchemaParseMode.WRITE)


@pytest.mark.parametrize(
    ("metadata_json", "expected_code", "expected_context"),
    [
        (
            _metadata([{"type": "text"}]),
            "flow_form_field_name_empty",
            {"field_index": 0},
        ),
        (
            _metadata(
                [
                    {"name": "case_id", "type": "text"},
                    {"name": "Case_ID", "type": "text"},
                ]
            ),
            "flow_form_field_name_duplicate",
            {"field_index": 1, "field_name": "Case_ID"},
        ),
        (
            _metadata([{"name": "flow_input", "type": "text"}]),
            "flow_form_field_name_namespace_head",
            {"field_index": 0, "field_name": "flow_input"},
        ),
        (
            _metadata([{"name": "text", "type": "text"}]),
            "flow_form_field_name_primary_input_key",
            {"field_index": 0, "field_name": "text"},
        ),
        (
            _metadata([{"name": "step_1", "type": "text"}]),
            "flow_form_field_name_step_alias",
            {"field_index": 0, "field_name": "step_1"},
        ),
    ],
)
def test_parse_flow_form_schema_preserves_write_error_codes_and_context(
    metadata_json: dict[str, object],
    expected_code: str,
    expected_context: dict[str, object],
) -> None:
    with pytest.raises(BadRequestException) as exc_info:
        parse_flow_form_schema(metadata_json, mode=FlowFormSchemaParseMode.WRITE)

    assert exc_info.value.code == expected_code
    assert exc_info.value.context == expected_context


def test_parse_flow_form_schema_normalizes_legacy_field_types() -> None:
    parsed = parse_flow_form_schema(
        _metadata(
            [
                {"name": "customer", "type": "string"},
                {"name": "email", "type": "email"},
                {"name": "notes", "type": "textarea"},
            ]
        ),
        mode=FlowFormSchemaParseMode.WRITE,
    )

    assert parsed is not None
    assert [field.type for field in parsed.fields] == [
        FlowFormFieldType.TEXT,
        FlowFormFieldType.TEXT,
        FlowFormFieldType.TEXT,
    ]


def test_serialize_flow_form_schema_preserves_explicit_shape_and_extra_keys() -> None:
    parsed = parse_flow_form_schema(
        {
            "form_schema": {
                "version": 1,
                "fields": [
                    {
                        "name": "customer",
                        "type": "string",
                        "x-ui": {"width": "full"},
                    }
                ],
            }
        },
        mode=FlowFormSchemaParseMode.WRITE,
    )

    assert parsed is not None
    assert serialize_flow_form_schema(parsed) == {
        "version": 1,
        "fields": [
            {
                "name": "customer",
                "type": "text",
                "x-ui": {"width": "full"},
            }
        ],
    }


@pytest.mark.parametrize(
    "metadata_json",
    [
        None,
        {},
        {"form_schema": None},
        {"form_schema": []},
        {"form_schema": {"fields": "not-a-list"}},
    ],
)
def test_parse_flow_form_schema_persisted_read_tolerates_unusable_top_level_shape(
    metadata_json: dict[str, object] | None,
) -> None:
    assert (
        parse_flow_form_schema(
            metadata_json, mode=FlowFormSchemaParseMode.PERSISTED_READ
        )
        is None
    )


def test_parse_flow_form_schema_persisted_read_tolerates_invalid_field_flags() -> None:
    parsed = parse_flow_form_schema(
        _metadata(
            [
                {
                    "name": "case_id",
                    "type": "text",
                    "required": "yes",
                    "order": 0,
                }
            ]
        ),
        mode=FlowFormSchemaParseMode.PERSISTED_READ,
    )

    assert parsed is not None
    assert parsed.fields[0].required is False
    assert parsed.fields[0].order is None


def test_parse_flow_form_schema_persisted_read_rejects_duplicate_options() -> None:
    with pytest.raises(
        BadRequestException,
        match=re.escape(
            "metadata_json.form_schema.fields[0].options[1] must be unique."
        ),
    ):
        parse_flow_form_schema(
            _metadata(
                [
                    {
                        "name": "category",
                        "type": "select",
                        "options": ["a", "A"],
                    }
                ]
            ),
            mode=FlowFormSchemaParseMode.PERSISTED_READ,
        )


@pytest.mark.parametrize(
    "mode",
    [FlowMetadataParseMode.WRITE, FlowMetadataParseMode.PERSISTED_READ],
)
def test_parse_flow_metadata_preserves_unrelated_top_level_keys(
    mode: FlowMetadataParseMode,
) -> None:
    parsed = parse_flow_metadata(
        {
            "form_schema": {
                "fields": [{"name": "case_id", "type": "string"}],
            },
            "care_data_policy": {"sensitive": True},
            "ai_builder": {"description": "Generated draft"},
            "transcription": {"language": "sv"},
        },
        mode=mode,
    )

    assert serialize_flow_metadata(parsed) == {
        "form_schema": {
            "fields": [{"name": "case_id", "type": "text"}],
        },
        "care_data_policy": {"sensitive": True},
        "ai_builder": {"description": "Generated draft"},
        "transcription": {"language": "sv"},
    }


def test_flow_care_data_policy_v1_defaults_to_non_sensitive() -> None:
    policy = FlowCareDataPolicyV1()

    assert policy.sensitive is False
    assert policy.approval_mode is None
    assert policy.pre_approval_visibility is None


def test_parse_flow_metadata_composes_existing_form_schema_model() -> None:
    parsed = parse_flow_metadata(
        {
            "form_schema": {
                "fields": [{"name": "customer", "type": "textarea"}],
            }
        },
        mode=FlowMetadataParseMode.WRITE,
    )

    assert parsed.form_schema is not None
    assert parsed.form_schema.fields[0].type is FlowFormFieldType.TEXT
    assert parsed.care_data_policy.sensitive is False
