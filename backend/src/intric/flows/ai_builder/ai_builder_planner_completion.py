"""Planner-union LLM completion boundary.

This module owns the provider call and provider-response normalization for
planner turns. The orchestration pipeline owns retry flow, and repair owns
corrective prompt construction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from intric.flows.ai_builder.ai_builder_token_usage import (
    CompletionTokenUsage,
    completion_token_usage_from_response,
)


@dataclass(frozen=True, slots=True)
class CompletionMetadata:
    finish_reason: str | None
    usage: CompletionTokenUsage


@dataclass(frozen=True, slots=True)
class PlannerCompletionResult:
    raw_content: str
    metadata: CompletionMetadata


async def call_planner_completion(
    *,
    litellm_client: Any,
    litellm_model: str,
    litellm_kwargs: Mapping[str, Any],
    messages: list[dict[str, Any]],
) -> PlannerCompletionResult:
    response = await litellm_client.acompletion(
        model=litellm_model,
        messages=messages,
        **litellm_kwargs,
    )
    raw_content, finish_reason = _choice_content_and_finish_reason(response)
    return PlannerCompletionResult(
        raw_content=raw_content,
        metadata=_completion_metadata_from_response(
            response,
            litellm_model=litellm_model,
            messages=messages,
            completion_text=raw_content,
            finish_reason=finish_reason,
        ),
    )


def _choice_content_and_finish_reason(response: object) -> tuple[str, str | None]:
    choices_value: object = getattr(response, "choices", None)
    if not isinstance(choices_value, Sequence) or isinstance(
        choices_value, (str, bytes)
    ):
        return "", None
    choices = cast(Sequence[object], choices_value)
    if not choices:
        return "", None

    choice = choices[0]
    message: object | None = getattr(choice, "message", None)
    content = getattr(message, "content", None)
    finish_reason = getattr(choice, "finish_reason", None)
    return (
        content if isinstance(content, str) else "",
        finish_reason if isinstance(finish_reason, str) else None,
    )


def _completion_metadata_from_response(
    response: object,
    *,
    litellm_model: str,
    messages: Sequence[Mapping[str, Any]],
    completion_text: str,
    finish_reason: str | None,
) -> CompletionMetadata:
    usage = completion_token_usage_from_response(
        response,
        model_name=litellm_model,
        messages=messages,
        completion_text=completion_text,
    )
    return CompletionMetadata(
        finish_reason=finish_reason,
        usage=usage,
    )


__all__ = [
    "CompletionMetadata",
    "PlannerCompletionResult",
    "call_planner_completion",
]
