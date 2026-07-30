from __future__ import annotations

from collections.abc import Mapping
from typing import cast

AI_BUILDER_BUDGET_MIN_TOKENS = 1
AI_BUILDER_BUDGET_MAX_TOKENS = 10_000_000
# These are platform safety ceilings, not organization policy defaults. They
# bound API collection work, persisted message size, synchronous DOCX
# decompression, and placeholder evidence respectively. Tenant admins choose
# the effective values up to these ceilings; raising a ceiling requires the
# release capacity proof recorded in the Flow production roadmap.
AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT = 100
AI_BUILDER_MAX_MESSAGE_CHARS_HARD_LIMIT = 50_000
AI_BUILDER_TEMPLATE_INSPECTION_HARD_LIMIT_BYTES = 200 * 1024 * 1024
AI_BUILDER_MAX_TEMPLATE_PLACEHOLDERS_HARD_LIMIT = 10_000
# This effective default remains admin-changeable and deliberately below the
# parser ceiling so normal sessions cannot consume the full safety envelope.
AI_BUILDER_DEFAULT_MAX_TEMPLATE_PLACEHOLDERS = 1_000
AI_BUILDER_BUDGET_FIELDS = frozenset(
    {
        "conversation_safety_buffer_tokens",
        "minimum_conversation_budget_tokens",
        "max_attachments",
        "max_message_chars",
        "max_template_inspection_uncompressed_bytes",
        "max_template_placeholders",
    }
)


def extract_ai_builder_budget_settings(
    tenant_flow_settings: Mapping[str, object] | None,
) -> dict[str, object]:
    if not isinstance(tenant_flow_settings, Mapping):
        return {}

    ai_builder = tenant_flow_settings.get("ai_builder")
    if not isinstance(ai_builder, Mapping):
        return {}

    return _copy_string_key_mapping(cast(Mapping[object, object], ai_builder))


def parse_ai_builder_budget_token(
    value: object,
    field_name: str,
    *,
    allow_none: bool = False,
) -> int | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    if value < AI_BUILDER_BUDGET_MIN_TOKENS or value > AI_BUILDER_BUDGET_MAX_TOKENS:
        raise ValueError(
            f"{field_name} must be between {AI_BUILDER_BUDGET_MIN_TOKENS} "
            f"and {AI_BUILDER_BUDGET_MAX_TOKENS}."
        )
    return value


def parse_ai_builder_operating_limit(value: object, field_name: str) -> int:
    hard_limits = {
        "max_attachments": AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT,
        "max_message_chars": AI_BUILDER_MAX_MESSAGE_CHARS_HARD_LIMIT,
        "max_template_inspection_uncompressed_bytes": (
            AI_BUILDER_TEMPLATE_INSPECTION_HARD_LIMIT_BYTES
        ),
        "max_template_placeholders": (AI_BUILDER_MAX_TEMPLATE_PLACEHOLDERS_HARD_LIMIT),
    }
    setting_name = field_name.rsplit(".", 1)[-1]
    hard_limit = hard_limits[setting_name]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    if value < 1 or value > hard_limit:
        raise ValueError(f"{field_name} must be between 1 and {hard_limit}.")
    return value


def validate_ai_builder_budget_settings_object(
    value: object,
) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("flow_settings.ai_builder must be an object")

    value_dict = _copy_string_key_mapping(cast(Mapping[object, object], value))
    unknown_fields = set(value_dict) - AI_BUILDER_BUDGET_FIELDS
    if unknown_fields:
        unknown = ", ".join(sorted(unknown_fields))
        raise ValueError(f"flow_settings.ai_builder contains unknown fields: {unknown}")

    validated: dict[str, object] = {}
    for field_name in (
        "conversation_safety_buffer_tokens",
        "minimum_conversation_budget_tokens",
    ):
        if field_name in value_dict:
            validated[field_name] = parse_ai_builder_budget_token(
                value_dict[field_name],
                f"flow_settings.ai_builder.{field_name}",
            )
    for field_name in (
        "max_attachments",
        "max_message_chars",
        "max_template_inspection_uncompressed_bytes",
        "max_template_placeholders",
    ):
        if field_name in value_dict:
            validated[field_name] = parse_ai_builder_operating_limit(
                value_dict[field_name],
                f"flow_settings.ai_builder.{field_name}",
            )
    return validated


def _copy_string_key_mapping(value: Mapping[object, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for raw_key, raw_value in value.items():
        if isinstance(raw_key, str):
            result[raw_key] = raw_value
            continue
        result[str(raw_key)] = raw_value
    return result
