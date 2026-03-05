from __future__ import annotations

from copy import deepcopy

import pytest

from intric.flows.flow_run_input_payload import normalize_and_validate_flow_run_payload
from intric.main.exceptions import BadRequestException


def _metadata(fields: list[dict[str, object]]) -> dict[str, object]:
    return {"form_schema": {"fields": fields}}


@pytest.mark.parametrize(
    "metadata_json",
    [
        None,
        {},
        {"form_schema": None},
        {"form_schema": {}},
        {"form_schema": {"fields": "invalid"}},
        {"form_schema": {"fields": []}},
    ],
)
def test_payload_passthrough_when_form_schema_missing_or_invalid(
    metadata_json: dict[str, object] | None,
) -> None:
    payload = {"note": "raw payload value", "file_ids": ["abc"]}

    normalized = normalize_and_validate_flow_run_payload(
        metadata_json=metadata_json,
        payload=payload,
    )

    assert normalized == payload


def test_missing_required_field_emits_machine_readable_error_contract() -> None:
    metadata = _metadata(
        [{"name": "case_id", "type": "text", "required": True, "order": 1}]
    )

    with pytest.raises(BadRequestException, match=r"Missing required input field 'case_id'\.") as exc_info:
        normalize_and_validate_flow_run_payload(metadata_json=metadata, payload={})

    assert exc_info.value.code == "flow_input_required_field_missing"
    assert exc_info.value.context == {
        "field_name": "case_id",
        "field_type": "text",
    }


@pytest.mark.parametrize(
    ("field_type", "value", "message", "code"),
    [
        ("text", None, r"Missing required input field 'field'\.", "flow_input_required_field_missing"),
        ("text", "   ", r"Field 'field' cannot be empty\.", "flow_input_required_field_empty"),
        (
            "number",
            None,
            r"Missing required input field 'field'\.",
            "flow_input_required_field_missing",
        ),
        ("number", "   ", r"Field 'field' cannot be empty\.", "flow_input_required_field_empty"),
        ("date", None, r"Missing required input field 'field'\.", "flow_input_required_field_missing"),
        ("date", "   ", r"Field 'field' cannot be empty\.", "flow_input_required_field_empty"),
        (
            "select",
            None,
            r"Missing required input field 'field'\.",
            "flow_input_required_field_missing",
        ),
        ("select", "   ", r"Field 'field' cannot be empty\.", "flow_input_required_field_empty"),
        (
            "multiselect",
            None,
            r"Missing required input field 'field'\.",
            "flow_input_required_field_missing",
        ),
        (
            "multiselect",
            [],
            r"Field 'field' must contain at least one value\.",
            "flow_input_required_field_empty",
        ),
        (
            "multiselect",
            " , ",
            r"Field 'field' must contain at least one value\.",
            "flow_input_required_field_empty",
        ),
    ],
)
def test_required_field_rejects_none_and_blank(
    field_type: str,
    value: object,
    message: str,
    code: str,
) -> None:
    field: dict[str, object] = {
        "name": "field",
        "type": field_type,
        "required": True,
        "order": 1,
    }
    if field_type in {"select", "multiselect"}:
        field["options"] = ["a", "b"]
    metadata = _metadata([field])

    with pytest.raises(BadRequestException, match=message) as exc_info:
        normalize_and_validate_flow_run_payload(
            metadata_json=metadata,
            payload={"field": value},
        )

    assert exc_info.value.code == code
    assert exc_info.value.context == {
        "field_name": "field",
        "field_type": field_type,
    }


def test_legacy_string_type_is_normalized_to_text() -> None:
    metadata = _metadata(
        [{"name": "note", "type": "string", "required": True, "order": 1}]
    )

    normalized = normalize_and_validate_flow_run_payload(
        metadata_json=metadata,
        payload={"note": 123},
    )

    assert normalized == {"note": "123"}


def test_unknown_fields_are_preserved_and_payload_is_not_mutated() -> None:
    metadata = _metadata(
        [{"name": "patient", "type": "text", "required": True, "order": 1}]
    )
    payload = {"patient": 123, "trace_id": "abc-123"}
    original_payload = deepcopy(payload)

    normalized = normalize_and_validate_flow_run_payload(
        metadata_json=metadata,
        payload=payload,
    )

    assert normalized == {"patient": "123", "trace_id": "abc-123"}
    assert payload == original_payload


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("1e3", 1000.0),
        ("2E-2", 0.02),
    ],
)
def test_number_field_accepts_scientific_notation(raw_value: str, expected: float) -> None:
    metadata = _metadata(
        [{"name": "attempts", "type": "number", "required": True, "order": 1}]
    )

    normalized = normalize_and_validate_flow_run_payload(
        metadata_json=metadata,
        payload={"attempts": raw_value},
    )

    assert normalized == {"attempts": expected}


@pytest.mark.parametrize(
    "raw_value",
    [
        "1e309",
        float("inf"),
        float("-inf"),
        float("nan"),
    ],
)
def test_number_field_rejects_non_finite_values(raw_value: object) -> None:
    metadata = _metadata(
        [{"name": "attempts", "type": "number", "required": True, "order": 1}]
    )

    with pytest.raises(BadRequestException, match=r"Field 'attempts' must be a finite number\.") as exc_info:
        normalize_and_validate_flow_run_payload(
            metadata_json=metadata,
            payload={"attempts": raw_value},
        )

    assert exc_info.value.code == "flow_input_invalid_number"
    assert exc_info.value.context == {
        "field_name": "attempts",
        "field_type": "number",
    }


def test_optional_select_empty_string_normalizes_to_none() -> None:
    metadata = _metadata(
        [
            {
                "name": "priority",
                "type": "select",
                "required": False,
                "order": 1,
                "options": ["low", "medium", "high"],
            }
        ]
    )

    normalized = normalize_and_validate_flow_run_payload(
        metadata_json=metadata,
        payload={"priority": "   "},
    )

    assert normalized == {"priority": None}


def test_multiselect_string_payload_is_split_and_trimmed() -> None:
    metadata = _metadata(
        [
            {
                "name": "tags",
                "type": "multiselect",
                "required": True,
                "order": 1,
                "options": ["care", "follow-up", "legal"],
            }
        ]
    )

    normalized = normalize_and_validate_flow_run_payload(
        metadata_json=metadata,
        payload={"tags": " care, follow-up "},
    )

    assert normalized == {"tags": ["care", "follow-up"]}


def test_optional_number_empty_string_normalizes_to_none() -> None:
    metadata = _metadata(
        [{"name": "attempts", "type": "number", "required": False, "order": 1}]
    )

    normalized = normalize_and_validate_flow_run_payload(
        metadata_json=metadata,
        payload={"attempts": "   "},
    )

    assert normalized == {"attempts": None}


def test_optional_date_allows_empty_string_and_normalizes_to_none() -> None:
    metadata = _metadata(
        [{"name": "visit_date", "type": "date", "required": False, "order": 1}]
    )

    normalized = normalize_and_validate_flow_run_payload(
        metadata_json=metadata,
        payload={"visit_date": "   "},
    )

    assert normalized == {"visit_date": None}


@pytest.mark.parametrize(
    ("field", "payload", "expected_code", "expected_context", "message"),
    [
        (
            {
                "name": "priority",
                "type": "select",
                "required": True,
                "order": 1,
                "options": ["low", "medium", "high"],
            },
            {"priority": 5},
            "flow_input_type_mismatch",
            {"field_name": "priority", "field_type": "select"},
            "must be a string",
        ),
        (
            {
                "name": "priority",
                "type": "select",
                "required": True,
                "order": 1,
                "options": ["low", "medium", "high"],
            },
            {"priority": "urgent"},
            "flow_input_invalid_option",
            {"field_name": "priority", "field_type": "select"},
            "must be one of the configured options",
        ),
        (
            {"name": "tags", "type": "multiselect", "required": True, "order": 1},
            {"tags": 42},
            "flow_input_invalid_multiselect_type",
            {"field_name": "tags", "field_type": "multiselect"},
            "must be an array of strings",
        ),
        (
            {"name": "tags", "type": "multiselect", "required": True, "order": 1},
            {"tags": ["care", 42]},
            "flow_input_invalid_multiselect_value",
            {"field_name": "tags", "field_type": "multiselect"},
            "must contain only string options",
        ),
        (
            {
                "name": "tags",
                "type": "multiselect",
                "required": True,
                "order": 1,
                "options": ["care", "follow-up", "legal"],
            },
            {"tags": ["care", "unknown"]},
            "flow_input_invalid_option",
            {"field_name": "tags", "field_type": "multiselect"},
            "contains invalid option values",
        ),
        (
            {"name": "attempts", "type": "number", "required": True, "order": 1},
            {"attempts": True},
            "flow_input_invalid_number",
            {"field_name": "attempts", "field_type": "number"},
            "must be a valid number",
        ),
        (
            {"name": "attempts", "type": "number", "required": True, "order": 1},
            {"attempts": "two"},
            "flow_input_invalid_number",
            {"field_name": "attempts", "field_type": "number"},
            "must be a valid number",
        ),
        (
            {"name": "visit_date", "type": "date", "required": True, "order": 1},
            {"visit_date": "2026/03/05"},
            "flow_input_invalid_date",
            {"field_name": "visit_date", "field_type": "date"},
            "must be a valid ISO date",
        ),
    ],
)
def test_field_validation_errors_emit_machine_readable_code_and_context(
    field: dict[str, object],
    payload: dict[str, object],
    expected_code: str,
    expected_context: dict[str, str],
    message: str,
) -> None:
    metadata = _metadata([field])

    with pytest.raises(BadRequestException, match=message) as exc_info:
        normalize_and_validate_flow_run_payload(
            metadata_json=metadata,
            payload=payload,
        )

    assert exc_info.value.code == expected_code
    assert exc_info.value.context == expected_context
