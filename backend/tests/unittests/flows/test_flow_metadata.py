from __future__ import annotations

import re

import pytest

from eneo.flows.flow_metadata import (
    FlowCareDataPolicy,
    FlowFormFieldType,
    FlowFormSchemaParseMode,
    FlowMetadataParseMode,
    parse_flow_form_schema,
    parse_flow_metadata,
    serialize_flow_metadata,
    validate_form_field_runtime_name,
)
from eneo.main.exceptions import BadRequestException


def _metadata(fields: list[dict[str, object]]) -> dict[str, object]:
    return {"form_schema": {"fields": fields}}


def _ai_builder_origin() -> dict[str, object]:
    return {
        "builder_session_id": "00000000-0000-0000-0000-000000000001",
        "builder_plan_id": "00000000-0000-0000-0000-000000000002",
        "builder_spec_hash": "spec-hash",
        "applied_at": "2026-07-01T12:00:00+00:00",
    }


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
            _metadata([{"name": "case_id", "type": "text", "label": 123}]),
            "metadata_json.form_schema.fields[0].label must be a string.",
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
        (
            _metadata([{"name": "names", "type": "list", "options": ["a"]}]),
            "metadata_json.form_schema.fields[0].options is only valid for select or multiselect.",
        ),
        (
            _metadata([{"name": "case_id", "type": "multiselect", "options": []}]),
            "metadata_json.form_schema.fields[0].options must contain at least one "
            "option for multiselect. Use type 'list' for free entry.",
        ),
        (
            _metadata([{"name": "case_id", "type": "select", "options": []}]),
            "metadata_json.form_schema.fields[0].options must contain at least one "
            "option for select.",
        ),
        (
            _metadata([{"name": "step_1", "type": "text"}]),
            "Form field 1 is named 'step_1'. Names like step_1 are reserved for "
            "Flow step aliases. Use a descriptive field name instead.",
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
            _metadata([{"name": "expected_flow_version", "type": "text"}]),
            "flow_form_field_name_primary_input_key",
            {"field_index": 0, "field_name": "expected_flow_version"},
        ),
        (
            _metadata([{"name": "step_inputs", "type": "text"}]),
            "flow_form_field_name_primary_input_key",
            {"field_index": 0, "field_name": "step_inputs"},
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


def test_validate_form_field_runtime_name_rejects_step_alias_with_neutral_error() -> (
    None
):
    with pytest.raises(BadRequestException) as exc_info:
        validate_form_field_runtime_name(1, "Step_2")

    assert str(exc_info.value) == (
        "Form field 2 is named 'Step_2'. Names like step_1 are reserved for "
        "Flow step aliases. Use a descriptive field name instead."
    )
    assert exc_info.value.code == "flow_form_field_name_step_alias"
    assert exc_info.value.context == {"field_index": 1, "field_name": "Step_2"}


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


def test_serialize_flow_metadata_preserves_form_schema_shape_and_extra_keys() -> None:
    parsed = parse_flow_metadata(
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
        mode=FlowMetadataParseMode.WRITE,
    )

    assert serialize_flow_metadata(parsed) == {
        "form_schema": {
            "version": 1,
            "fields": [
                {
                    "name": "customer",
                    "type": "text",
                    "x-ui": {"width": "full"},
                }
            ],
        }
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


def test_parse_flow_metadata_rejects_unknown_top_level_keys_on_write() -> None:
    with pytest.raises(
        BadRequestException,
        match=re.escape(
            "metadata_json contains unknown top-level fields: transcription"
        ),
    ):
        parse_flow_metadata(
            {
                "form_schema": {
                    "fields": [{"name": "case_id", "type": "string"}],
                },
                "transcription": {"language": "sv"},
            },
            mode=FlowMetadataParseMode.WRITE,
        )


def test_parse_flow_metadata_refuses_the_retired_ai_builder_origin_on_write() -> None:
    with pytest.raises(
        BadRequestException,
        match=re.escape("metadata_json contains unknown top-level fields: ai_builder"),
    ):
        parse_flow_metadata(
            {"ai_builder": {"origin": _ai_builder_origin()}},
            mode=FlowMetadataParseMode.WRITE,
        )


def test_parse_flow_metadata_persisted_read_drops_unowned_metadata() -> None:
    parsed = parse_flow_metadata(
        {
            "form_schema": {
                "fields": [{"name": "case_id", "type": "string"}],
            },
            "care_data_policy": {"sensitive": True},
            "wizard": {"transcription_enabled": True, "custom_ui": "compact"},
            "ai_builder": {
                "origin": _ai_builder_origin(),
                "other": {"stale": True},
            },
            "transcription": {"language": "sv"},
        },
        mode=FlowMetadataParseMode.PERSISTED_READ,
    )

    assert serialize_flow_metadata(parsed) == {
        "form_schema": {
            "fields": [{"name": "case_id", "type": "text"}],
        },
        "care_data_policy": {"sensitive": True},
        "wizard": {"transcription_enabled": True, "custom_ui": "compact"},
    }


def test_flow_care_data_policy_defaults_to_non_sensitive() -> None:
    policy = FlowCareDataPolicy()

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


def test_flow_metadata_write_normalization_preserves_empty_care_data_policy() -> None:
    parsed = parse_flow_metadata(
        {"care_data_policy": {}},
        mode=FlowMetadataParseMode.WRITE,
    )

    assert serialize_flow_metadata(parsed) == {"care_data_policy": {}}


def test_flow_metadata_write_normalization_preserves_explicit_false_sensitive() -> None:
    parsed = parse_flow_metadata(
        {"care_data_policy": {"sensitive": False}},
        mode=FlowMetadataParseMode.WRITE,
    )

    assert serialize_flow_metadata(parsed) == {"care_data_policy": {"sensitive": False}}


def test_flow_metadata_persisted_read_fails_closed_for_legacy_sensitive() -> None:
    parsed = parse_flow_metadata(
        {"care_data_policy": {"sensitive": "yes"}},
        mode=FlowMetadataParseMode.PERSISTED_READ,
    )

    assert serialize_flow_metadata(parsed) == {"care_data_policy": {"sensitive": True}}


@pytest.mark.parametrize(
    ("metadata_json", "message"),
    [
        (
            {"care_data_policy": []},
            "metadata_json.care_data_policy must be an object.",
        ),
        (
            {"care_data_policy": {"unknown": True}},
            "metadata_json.care_data_policy contains unknown fields: unknown",
        ),
        (
            {"care_data_policy": {"sensitive": "yes"}},
            "metadata_json.care_data_policy.sensitive must be a boolean.",
        ),
        (
            {"care_data_policy": {"approval_mode": "two_reviewers"}},
            "metadata_json.care_data_policy.approval_mode must be 'single_reviewer_outside_flow' when provided.",
        ),
        (
            {"care_data_policy": {"pre_approval_visibility": "everyone"}},
            "metadata_json.care_data_policy.pre_approval_visibility must be 'uploader_and_reviewers' when provided.",
        ),
        # A list or object is no member of the allowed set and cannot be
        # looked up in it: refused like any other value, not a server error.
        (
            {"care_data_policy": {"approval_mode": ["single_reviewer_outside_flow"]}},
            "metadata_json.care_data_policy.approval_mode must be 'single_reviewer_outside_flow' when provided.",
        ),
        (
            {"care_data_policy": {"pre_approval_visibility": {}}},
            "metadata_json.care_data_policy.pre_approval_visibility must be 'uploader_and_reviewers' when provided.",
        ),
    ],
)
def test_parse_flow_metadata_preserves_care_data_write_errors(
    metadata_json: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(BadRequestException, match=re.escape(message)):
        parse_flow_metadata(metadata_json, mode=FlowMetadataParseMode.WRITE)


def test_list_field_is_accepted_without_options() -> None:
    parsed = parse_flow_metadata(
        _metadata([{"name": "names", "type": "list"}]),
        mode=FlowMetadataParseMode.WRITE,
    )
    assert parsed is not None
    field = parsed.form_schema.fields[0]
    assert field.type is FlowFormFieldType.LIST
    assert field.options is None


def test_persisted_read_tolerates_empty_options_on_multiselect() -> None:
    parsed = parse_flow_metadata(
        _metadata([{"name": "case_id", "type": "multiselect", "options": []}]),
        mode=FlowMetadataParseMode.PERSISTED_READ,
    )
    assert parsed is not None
    assert parsed.form_schema.fields[0].options == []


def test_flow_evidence_export_is_off_until_the_flow_allows_it() -> None:
    absent = parse_flow_metadata({}, mode=FlowMetadataParseMode.WRITE)

    assert absent.evidence_policy.allow_export is False
    assert serialize_flow_metadata(absent) == {}
    assert (
        parse_flow_metadata(
            None, mode=FlowMetadataParseMode.PERSISTED_READ
        ).evidence_policy.allow_export
        is False
    )


@pytest.mark.parametrize("allowed", [True, False])
def test_flow_evidence_policy_round_trips_an_explicit_choice(allowed: bool) -> None:
    parsed = parse_flow_metadata(
        {"evidence_policy": {"allow_export": allowed}},
        mode=FlowMetadataParseMode.WRITE,
    )

    assert parsed.evidence_policy.allow_export is allowed
    assert serialize_flow_metadata(parsed) == {
        "evidence_policy": {"allow_export": allowed}
    }


@pytest.mark.parametrize(
    ("policy", "message"),
    [
        ("yes", "metadata_json.evidence_policy must be an object."),
        (
            {"allow_export": "true"},
            "metadata_json.evidence_policy.allow_export must be a boolean.",
        ),
        (
            {"allow_export": 1},
            "metadata_json.evidence_policy.allow_export must be a boolean.",
        ),
        (
            {"allow_export": True, "allow_raw_export": True},
            "metadata_json.evidence_policy contains unknown fields: allow_raw_export",
        ),
    ],
)
def test_flow_evidence_policy_write_accepts_only_a_real_boolean(
    policy: object, message: str
) -> None:
    with pytest.raises(BadRequestException, match=re.escape(message)):
        parse_flow_metadata(
            {"evidence_policy": policy},
            mode=FlowMetadataParseMode.WRITE,
        )


@pytest.mark.parametrize(
    "stored",
    [
        "yes",
        1,
        [],
        {},
        {"allow_export": "true"},
        {"allow_export": 1},
        {"allow_export": None},
    ],
)
def test_flow_evidence_policy_persisted_read_enables_only_on_exact_true(
    stored: object,
) -> None:
    # An export switch that a corrupt value could open would not be a switch.
    parsed = parse_flow_metadata(
        {"evidence_policy": stored},
        mode=FlowMetadataParseMode.PERSISTED_READ,
    )

    assert parsed.evidence_policy.allow_export is False


@pytest.mark.parametrize("allowed", [True, False])
def test_flow_evidence_policy_persisted_read_keeps_a_stored_boolean(
    allowed: bool,
) -> None:
    parsed = parse_flow_metadata(
        {"evidence_policy": {"allow_export": allowed, "legacy": "ignored"}},
        mode=FlowMetadataParseMode.PERSISTED_READ,
    )

    assert parsed.evidence_policy.allow_export is allowed
    assert serialize_flow_metadata(parsed) == {
        "evidence_policy": {"allow_export": allowed}
    }


def test_a_text_field_can_name_the_run_and_a_date_field_date_it() -> None:
    parsed = parse_flow_form_schema(
        _metadata(
            [
                {"name": "meeting", "type": "text", "role": "run_label"},
                {"name": "held_on", "type": "date", "role": "run_date"},
                {"name": "notes", "type": "text"},
            ]
        ),
        mode=FlowFormSchemaParseMode.WRITE,
    )

    assert parsed is not None
    assert [field.role for field in parsed.fields] == ["run_label", "run_date", None]


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        (
            [{"name": "held_on", "type": "date", "role": "run_label"}],
            "metadata_json.form_schema.fields[0].role 'run_label' is only valid for a text field.",
        ),
        (
            [{"name": "meeting", "type": "text", "role": "run_date"}],
            "metadata_json.form_schema.fields[0].role 'run_date' is only valid for a date field.",
        ),
        (
            [{"name": "meeting", "type": "text", "role": "title"}],
            "metadata_json.form_schema.fields[0].role must be 'run_label' or 'run_date'.",
        ),
        (
            [
                {"name": "meeting", "type": "text", "role": "run_label"},
                {"name": "case", "type": "text", "role": "run_label"},
            ],
            "metadata_json.form_schema.fields[1].role 'run_label' is already on another field.",
        ),
    ],
)
def test_a_field_role_that_cannot_hold_is_refused_on_write(
    fields: list[dict[str, object]], message: str
) -> None:
    with pytest.raises(BadRequestException, match=re.escape(message)):
        parse_flow_form_schema(_metadata(fields), mode=FlowFormSchemaParseMode.WRITE)


def test_a_stored_role_that_cannot_hold_is_dropped_and_its_field_kept() -> None:
    parsed = parse_flow_metadata(
        _metadata(
            [
                {"name": "meeting", "type": "text", "role": "run_label"},
                {"name": "case", "type": "text", "role": "run_label"},
                {"name": "held_on", "type": "date", "role": "title"},
            ]
        ),
        mode=FlowMetadataParseMode.PERSISTED_READ,
    )

    assert serialize_flow_metadata(parsed) == _metadata(
        [
            {"name": "meeting", "type": "text", "role": "run_label"},
            {"name": "case", "type": "text"},
            {"name": "held_on", "type": "date"},
        ]
    )


def test_a_field_without_a_role_is_saved_without_one() -> None:
    parsed = parse_flow_metadata(
        _metadata([{"name": "meeting", "type": "text", "role": None}]),
        mode=FlowMetadataParseMode.WRITE,
    )

    assert serialize_flow_metadata(parsed) == _metadata(
        [{"name": "meeting", "type": "text"}]
    )
