from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.flow_ai_builder_budget_settings import (
    AI_BUILDER_DEFAULT_MAX_TEMPLATE_PLACEHOLDERS,
    AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT,
    AI_BUILDER_MAX_MESSAGE_CHARS_HARD_LIMIT,
    AI_BUILDER_TEMPLATE_INSPECTION_HARD_LIMIT_BYTES,
    extract_ai_builder_budget_settings,
    parse_ai_builder_budget_token,
    parse_ai_builder_operating_limit,
)
from eneo.main.config import get_settings


@dataclass(frozen=True)
class AIBuilderBudgetPolicy:
    conversation_safety_buffer_tokens: int
    minimum_conversation_budget_tokens: int
    max_attachments: int = AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT
    max_message_chars: int = AI_BUILDER_MAX_MESSAGE_CHARS_HARD_LIMIT
    max_template_inspection_uncompressed_bytes: int = (
        AI_BUILDER_TEMPLATE_INSPECTION_HARD_LIMIT_BYTES
    )
    max_template_placeholders: int = AI_BUILDER_DEFAULT_MAX_TEMPLATE_PLACEHOLDERS


def _default_policy(defaults: Any | None = None) -> AIBuilderBudgetPolicy:
    source = defaults or get_settings()
    return AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=int(
            source.ai_builder_conversation_safety_buffer_tokens
        ),
        minimum_conversation_budget_tokens=int(
            source.ai_builder_minimum_conversation_budget_tokens
        ),
        max_attachments=AI_BUILDER_MAX_ATTACHMENTS_HARD_LIMIT,
        max_message_chars=AI_BUILDER_MAX_MESSAGE_CHARS_HARD_LIMIT,
        max_template_inspection_uncompressed_bytes=(
            AI_BUILDER_TEMPLATE_INSPECTION_HARD_LIMIT_BYTES
        ),
        max_template_placeholders=AI_BUILDER_DEFAULT_MAX_TEMPLATE_PLACEHOLDERS,
    )


def _parse_token_int(
    value: Any, field_name: str, *, allow_none: bool = False
) -> int | None:
    try:
        return parse_ai_builder_budget_token(
            value,
            field_name,
            allow_none=allow_none,
        )
    except ValueError as error:
        raise AIBuilderBadRequestException(
            str(error),
            code=AIBuilderErrorCode.INVALID_AI_BUILDER_SETTINGS,
        ) from error


def resolve_ai_builder_budget_policy(
    tenant_flow_settings: dict[str, Any] | None,
    *,
    defaults: Any | None = None,
) -> AIBuilderBudgetPolicy:
    resolved_defaults = _default_policy(defaults)
    raw = extract_ai_builder_budget_settings(tenant_flow_settings)

    safety_buffer = resolved_defaults.conversation_safety_buffer_tokens
    if "conversation_safety_buffer_tokens" in raw:
        parsed_safety_buffer = _parse_token_int(
            raw["conversation_safety_buffer_tokens"],
            "conversation_safety_buffer_tokens",
        )
        if parsed_safety_buffer is not None:
            safety_buffer = parsed_safety_buffer

    minimum_budget = resolved_defaults.minimum_conversation_budget_tokens
    if "minimum_conversation_budget_tokens" in raw:
        parsed_minimum_budget = _parse_token_int(
            raw["minimum_conversation_budget_tokens"],
            "minimum_conversation_budget_tokens",
        )
        if parsed_minimum_budget is not None:
            minimum_budget = parsed_minimum_budget

    operating_limits = {
        "max_attachments": resolved_defaults.max_attachments,
        "max_message_chars": resolved_defaults.max_message_chars,
        "max_template_inspection_uncompressed_bytes": (
            resolved_defaults.max_template_inspection_uncompressed_bytes
        ),
        "max_template_placeholders": resolved_defaults.max_template_placeholders,
    }
    for field_name in operating_limits:
        if field_name not in raw:
            continue
        try:
            operating_limits[field_name] = parse_ai_builder_operating_limit(
                raw[field_name],
                field_name,
            )
        except ValueError as error:
            raise AIBuilderBadRequestException(
                str(error),
                code=AIBuilderErrorCode.INVALID_AI_BUILDER_SETTINGS,
            ) from error

    return AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=safety_buffer,
        minimum_conversation_budget_tokens=minimum_budget,
        max_attachments=operating_limits["max_attachments"],
        max_message_chars=operating_limits["max_message_chars"],
        max_template_inspection_uncompressed_bytes=operating_limits[
            "max_template_inspection_uncompressed_bytes"
        ],
        max_template_placeholders=operating_limits["max_template_placeholders"],
    )


def apply_ai_builder_budget_policy_patch(
    current_flow_settings: dict[str, Any] | None,
    *,
    conversation_safety_buffer_tokens: int | None = None,
    minimum_conversation_budget_tokens: int | None = None,
    max_attachments: int | None = None,
    max_message_chars: int | None = None,
    max_template_inspection_uncompressed_bytes: int | None = None,
    max_template_placeholders: int | None = None,
    remove_keys: set[str] | None = None,
) -> dict[str, Any]:
    result = (
        dict(current_flow_settings) if isinstance(current_flow_settings, dict) else {}
    )
    current = extract_ai_builder_budget_settings(result)
    next_settings: dict[str, Any] = dict(current)

    if conversation_safety_buffer_tokens is not None:
        next_settings["conversation_safety_buffer_tokens"] = _parse_token_int(
            conversation_safety_buffer_tokens,
            "conversation_safety_buffer_tokens",
        )
    if minimum_conversation_budget_tokens is not None:
        next_settings["minimum_conversation_budget_tokens"] = _parse_token_int(
            minimum_conversation_budget_tokens,
            "minimum_conversation_budget_tokens",
        )
    operating_updates = {
        "max_attachments": max_attachments,
        "max_message_chars": max_message_chars,
        "max_template_inspection_uncompressed_bytes": (
            max_template_inspection_uncompressed_bytes
        ),
        "max_template_placeholders": max_template_placeholders,
    }
    for field_name, value in operating_updates.items():
        if value is not None:
            next_settings[field_name] = parse_ai_builder_operating_limit(
                value,
                field_name,
            )

    for key in remove_keys or ():
        next_settings.pop(key, None)

    if next_settings:
        result["ai_builder"] = next_settings
    else:
        result.pop("ai_builder", None)
    return result
