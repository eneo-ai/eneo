from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException

_MIN_TOKENS = 1
_MAX_TOKENS = 10_000_000
_AI_BUILDER_BUDGET_FIELDS = {
    "conversation_safety_buffer_tokens",
    "minimum_conversation_budget_tokens",
    "unknown_model_context_window_tokens",
}


@dataclass(frozen=True)
class AIBuilderBudgetPolicy:
    conversation_safety_buffer_tokens: int
    minimum_conversation_budget_tokens: int
    unknown_model_context_window_tokens: int | None = None


def _default_policy(defaults: Any | None = None) -> AIBuilderBudgetPolicy:
    source = defaults or get_settings()
    return AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=int(
            source.ai_builder_conversation_safety_buffer_tokens
        ),
        minimum_conversation_budget_tokens=int(
            source.ai_builder_minimum_conversation_budget_tokens
        ),
        unknown_model_context_window_tokens=source.ai_builder_unknown_model_context_window_tokens,
    )


def _extract_ai_builder_settings(
    tenant_flow_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(tenant_flow_settings, dict):
        return {}

    ai_builder = tenant_flow_settings.get("ai_builder")
    if not isinstance(ai_builder, dict):
        return {}

    return ai_builder


def _parse_token_int(value: Any, field_name: str, *, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadRequestException(f"{field_name} must be an integer.")
    if value < _MIN_TOKENS or value > _MAX_TOKENS:
        raise BadRequestException(
            f"{field_name} must be between {_MIN_TOKENS} and {_MAX_TOKENS}."
        )
    return value


def validate_ai_builder_budget_settings_object(
    value: Any,
) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("flow_settings.ai_builder must be an object")

    unknown_fields = set(value) - _AI_BUILDER_BUDGET_FIELDS
    if unknown_fields:
        unknown = ", ".join(sorted(unknown_fields))
        raise ValueError(f"flow_settings.ai_builder contains unknown fields: {unknown}")

    validated: dict[str, Any] = {}
    for field_name in ("conversation_safety_buffer_tokens", "minimum_conversation_budget_tokens"):
        if field_name in value:
            validated[field_name] = _parse_token_int(
                value[field_name],
                f"flow_settings.ai_builder.{field_name}",
            )
    if "unknown_model_context_window_tokens" in value:
        validated["unknown_model_context_window_tokens"] = _parse_token_int(
            value["unknown_model_context_window_tokens"],
            "flow_settings.ai_builder.unknown_model_context_window_tokens",
            allow_none=True,
        )
    return validated


def resolve_ai_builder_budget_policy(
    tenant_flow_settings: dict[str, Any] | None,
    *,
    defaults: Any | None = None,
) -> AIBuilderBudgetPolicy:
    resolved_defaults = _default_policy(defaults)
    raw = _extract_ai_builder_settings(tenant_flow_settings)

    safety_buffer = resolved_defaults.conversation_safety_buffer_tokens
    if "conversation_safety_buffer_tokens" in raw:
        safety_buffer = int(
            _parse_token_int(
                raw["conversation_safety_buffer_tokens"],
                "conversation_safety_buffer_tokens",
            )
        )

    minimum_budget = resolved_defaults.minimum_conversation_budget_tokens
    if "minimum_conversation_budget_tokens" in raw:
        minimum_budget = int(
            _parse_token_int(
                raw["minimum_conversation_budget_tokens"],
                "minimum_conversation_budget_tokens",
            )
        )

    unknown_context_window = resolved_defaults.unknown_model_context_window_tokens
    if "unknown_model_context_window_tokens" in raw:
        unknown_context_window = _parse_token_int(
            raw["unknown_model_context_window_tokens"],
            "unknown_model_context_window_tokens",
            allow_none=True,
        )

    return AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=safety_buffer,
        minimum_conversation_budget_tokens=minimum_budget,
        unknown_model_context_window_tokens=unknown_context_window,
    )


def apply_ai_builder_budget_policy_patch(
    current_flow_settings: dict[str, Any] | None,
    *,
    conversation_safety_buffer_tokens: int | None = None,
    minimum_conversation_budget_tokens: int | None = None,
    unknown_model_context_window_tokens: int | None = None,
    remove_keys: set[str] | None = None,
) -> dict[str, Any]:
    result = (
        dict(current_flow_settings)
        if isinstance(current_flow_settings, dict)
        else {}
    )
    current = _extract_ai_builder_settings(result)
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
    if unknown_model_context_window_tokens is not None:
        next_settings["unknown_model_context_window_tokens"] = _parse_token_int(
            unknown_model_context_window_tokens,
            "unknown_model_context_window_tokens",
        )

    for key in remove_keys or ():
        next_settings.pop(key, None)

    if next_settings:
        result["ai_builder"] = next_settings
    else:
        result.pop("ai_builder", None)
    return result
