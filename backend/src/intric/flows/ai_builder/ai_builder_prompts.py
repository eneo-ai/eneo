# pyright: reportUnusedFunction=false

"""Prompt assembly and conversation trimming for the AI Flow Builder."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypeVar, cast

from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from intric.flows.ai_builder.ai_builder_flow_context import (
    build_flow_context,
    build_plan_summary,
    build_step_ref_mapping,
)
from intric.flows.ai_builder.ai_builder_requirements_state import (
    resolve_requirements_state,
)

__all__ = [
    "build_flow_context",
    "build_plan_summary",
    "build_step_ref_mapping",
    "compute_conversation_token_budget",
    "has_confirmed_requirements",
    "trim_conversation_for_context",
]

_MessageT = TypeVar("_MessageT", bound=Mapping[str, Any])


def compute_conversation_token_budget(
    *,
    litellm_model: str | None,
    model_max_input_tokens: int | None,
    system_prompt_tokens: int,
    max_output_tokens: int,
    safety_buffer_tokens: int,
    minimum_budget_tokens: int,
    unknown_model_context_window_tokens: int | None = None,
) -> int:
    """Compute available token budget for conversation history.

    Uses the model's actual context window (via LiteLLM) minus the system prompt,
    output reservation, and an explicit safety buffer. Uses the stored model
    budget or an explicit configured fallback when LiteLLM has no match.
    """
    from intric.model_providers.domain.model_defaults import lookup_model_defaults

    defaults = None
    if litellm_model:
        bare_name = litellm_model.split("/", 1)[-1] if "/" in litellm_model else None
        defaults = lookup_model_defaults(litellm_model, bare_name)

    context_window = (
        (defaults.max_input_tokens if defaults else None)
        or model_max_input_tokens
        or unknown_model_context_window_tokens
    )
    if context_window is None:
        raise ValueError("Planner model has no known context window.")

    budget = (
        context_window - system_prompt_tokens - max_output_tokens - safety_buffer_tokens
    )
    return max(budget, minimum_budget_tokens)


def trim_conversation_for_context(
    messages: list[_MessageT],
    *,
    max_tokens: int,
) -> list[_MessageT]:
    """Trim conversation history to fit within the provided token budget.

    The budget should come from compute_conversation_token_budget() which
    derives it from the model's actual context window.
    """
    if max_tokens >= _estimate_group_tokens(messages):
        return list(messages)

    groups: list[list[_MessageT]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        group = [message]
        if message.get("role") == "assistant" and message.get("tool_calls"):
            tool_index = index + 1
            while (
                tool_index < len(messages)
                and messages[tool_index].get("role") == "tool"
            ):
                group.append(messages[tool_index])
                tool_index += 1
            index = tool_index
        else:
            index += 1
        groups.append(group)

    kept_groups: list[list[_MessageT]] = []
    consumed_tokens = 0
    for group in reversed(groups):
        group_tokens = _estimate_group_tokens(group)
        if kept_groups and consumed_tokens + group_tokens > max_tokens:
            break
        kept_groups.append(group)
        consumed_tokens += group_tokens

    kept_groups.reverse()
    trimmed: list[_MessageT] = []
    for group in kept_groups:
        trimmed.extend(group)
    return trimmed


def _estimate_group_tokens(group: Sequence[Mapping[str, Any]]) -> int:
    return sum(_estimate_message_tokens(message) for message in group)


def _estimate_message_tokens(message: Mapping[str, Any]) -> int:
    chunks: list[str] = []
    content = message.get("content")
    if isinstance(content, str):
        chunks.append(content)

    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for tool_call in cast(list[object], tool_calls):
            chunks.append(str(tool_call))

    tool_call_id = message.get("tool_call_id")
    if isinstance(tool_call_id, str):
        chunks.append(tool_call_id)

    if not chunks:
        return 1

    # Use // 3 instead of // 4: Swedish compound words average fewer chars
    # per token than English, so the conservative factor prevents undercount.
    return max(1, sum(max(1, len(chunk) // 3) for chunk in chunks) + 4)


def has_confirmed_requirements(conversation: list[ConversationMessage]) -> bool:
    """Check if the latest requirements summary is confirmed."""
    return resolve_requirements_state(conversation).confirmed
