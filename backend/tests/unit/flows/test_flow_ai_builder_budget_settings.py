from __future__ import annotations

import pytest

from eneo.flows.flow_ai_builder_budget_settings import (
    AI_BUILDER_BUDGET_MAX_TOKENS,
    AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT,
    AI_BUILDER_MAX_MESSAGE_CHARS_HARD_LIMIT,
    AI_BUILDER_MAX_TEMPLATE_PLACEHOLDERS_HARD_LIMIT,
    AI_BUILDER_TEMPLATE_INSPECTION_HARD_LIMIT_BYTES,
    extract_ai_builder_budget_settings,
    parse_ai_builder_budget_token,
    parse_ai_builder_operating_limit,
    validate_ai_builder_budget_settings_object,
)


@pytest.mark.parametrize("value", [None, [], "invalid"])
def test_extract_budget_settings_rejects_non_mapping_roots(value: object) -> None:
    assert extract_ai_builder_budget_settings(value) == {}


@pytest.mark.parametrize("value", [{}, {"ai_builder": None}, {"ai_builder": []}])
def test_extract_budget_settings_rejects_non_mapping_builder_values(
    value: object,
) -> None:
    assert extract_ai_builder_budget_settings(value) == {}


def test_extract_budget_settings_copies_all_entries_and_normalizes_keys() -> None:
    source = {
        "ai_builder": {
            "max_attachments": 7,
            "max_message_chars": 8,
            9: "unknown",
        }
    }

    extracted = extract_ai_builder_budget_settings(source)

    assert extracted == {
        "max_attachments": 7,
        "max_message_chars": 8,
        "9": "unknown",
    }
    assert extracted is not source["ai_builder"]


def test_token_budget_accepts_only_integer_values_inside_closed_bounds() -> None:
    assert parse_ai_builder_budget_token(1, "budget") == 1
    assert (
        parse_ai_builder_budget_token(AI_BUILDER_BUDGET_MAX_TOKENS, "budget")
        == AI_BUILDER_BUDGET_MAX_TOKENS
    )
    assert parse_ai_builder_budget_token(None, "budget", allow_none=True) is None


@pytest.mark.parametrize("value", [None, True, False, 1.0, "1"])
def test_token_budget_rejects_non_integer_values(value: object) -> None:
    with pytest.raises(ValueError, match=r"^budget must be an integer\.$"):
        parse_ai_builder_budget_token(value, "budget")


@pytest.mark.parametrize("value", [0, AI_BUILDER_BUDGET_MAX_TOKENS + 1])
def test_token_budget_rejects_values_outside_closed_bounds(value: int) -> None:
    with pytest.raises(
        ValueError,
        match=(rf"^budget must be between 1 and {AI_BUILDER_BUDGET_MAX_TOKENS}\.$"),
    ):
        parse_ai_builder_budget_token(value, "budget")


@pytest.mark.parametrize(
    ("setting", "hard_limit"),
    [
        ("max_attachments", AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT),
        ("max_message_chars", AI_BUILDER_MAX_MESSAGE_CHARS_HARD_LIMIT),
        (
            "max_template_inspection_uncompressed_bytes",
            AI_BUILDER_TEMPLATE_INSPECTION_HARD_LIMIT_BYTES,
        ),
        (
            "max_template_placeholders",
            AI_BUILDER_MAX_TEMPLATE_PLACEHOLDERS_HARD_LIMIT,
        ),
    ],
)
def test_operating_limits_use_each_named_closed_hard_limit(
    setting: str,
    hard_limit: int,
) -> None:
    field_name = f"flow_settings.ai_builder.{setting}"
    assert parse_ai_builder_operating_limit(1, field_name) == 1
    assert parse_ai_builder_operating_limit(hard_limit, field_name) == hard_limit
    for value in (0, hard_limit + 1):
        with pytest.raises(
            ValueError,
            match=rf"^{field_name} must be between 1 and {hard_limit}\.$",
        ):
            parse_ai_builder_operating_limit(value, field_name)


@pytest.mark.parametrize("value", [None, True, False, 1.0, "1"])
def test_operating_limits_reject_non_integer_values(value: object) -> None:
    field_name = "flow_settings.ai_builder.max_attachments"
    with pytest.raises(
        ValueError,
        match=rf"^{field_name} must be an integer\.$",
    ):
        parse_ai_builder_operating_limit(value, field_name)


def test_budget_settings_validation_accepts_every_supported_field() -> None:
    value = {
        "conversation_safety_buffer_tokens": 2,
        "minimum_conversation_budget_tokens": 3,
        "max_attachments": 4,
        "max_message_chars": 5,
        "max_template_inspection_uncompressed_bytes": 6,
        "max_template_placeholders": 7,
    }

    assert validate_ai_builder_budget_settings_object(value) == value


def test_budget_settings_validation_rejects_non_objects_and_sorted_unknowns() -> None:
    assert validate_ai_builder_budget_settings_object(None) == {}
    with pytest.raises(
        ValueError,
        match=r"^flow_settings\.ai_builder must be an object$",
    ):
        validate_ai_builder_budget_settings_object([])
    with pytest.raises(
        ValueError,
        match=(
            r"^flow_settings\.ai_builder contains unknown fields: "
            r"10, alpha, omega$"
        ),
    ):
        validate_ai_builder_budget_settings_object({"omega": 1, "alpha": 2, 10: 3})


@pytest.mark.parametrize(
    ("field_name", "value", "expected_message"),
    [
        (
            "conversation_safety_buffer_tokens",
            0,
            f"flow_settings.ai_builder.conversation_safety_buffer_tokens must be "
            f"between 1 and {AI_BUILDER_BUDGET_MAX_TOKENS}.",
        ),
        (
            "max_attachments",
            AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT + 1,
            "flow_settings.ai_builder.max_attachments must be between 1 and "
            f"{AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT}.",
        ),
    ],
)
def test_budget_settings_validation_delegates_field_bounds(
    field_name: str,
    value: object,
    expected_message: str,
) -> None:
    with pytest.raises(ValueError) as exc_info:
        validate_ai_builder_budget_settings_object({field_name: value})
    assert str(exc_info.value) == expected_message
