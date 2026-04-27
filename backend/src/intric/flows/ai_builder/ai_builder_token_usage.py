from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from intric.tokens.token_utils import count_tokens

TokenUsageSource = Literal["provider", "litellm_estimate", "none"]

TOKEN_USAGE_SOURCE_PROVIDER: TokenUsageSource = "provider"
TOKEN_USAGE_SOURCE_ESTIMATE: TokenUsageSource = "litellm_estimate"
TOKEN_USAGE_SOURCE_NONE: TokenUsageSource = "none"


@dataclass(frozen=True, slots=True)
class CompletionTokenUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    source: TokenUsageSource = TOKEN_USAGE_SOURCE_NONE
    estimated: bool = False

    @property
    def has_tokens(self) -> bool:
        return any(
            value is not None
            for value in (
                self.prompt_tokens,
                self.completion_tokens,
                self.total_tokens,
            )
        )


def completion_token_usage_from_response(
    response: Any,
    *,
    model_name: str,
    messages: Sequence[Mapping[str, Any]],
    completion_text: str,
) -> CompletionTokenUsage:
    """Extract provider usage or estimate it at the LLM boundary.

    The rest of AI Builder should not know provider response shapes. Keeping
    the fallback at the call boundary preserves the committed-turn telemetry
    contract while making missing `response.usage` visible to the UI.
    """

    provider_usage = _provider_usage(response)
    if provider_usage.has_tokens:
        return provider_usage

    prompt_text = _render_messages_for_counting(messages)
    prompt_tokens = count_tokens(prompt_text, model_name)
    completion_tokens = count_tokens(completion_text, model_name)
    return CompletionTokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        source=TOKEN_USAGE_SOURCE_ESTIMATE,
        estimated=True,
    )


def combine_token_usage(usages: Sequence[CompletionTokenUsage]) -> CompletionTokenUsage:
    present = [usage for usage in usages if usage.has_tokens]
    if not present:
        return CompletionTokenUsage()

    prompt_tokens = sum(_non_negative_int(usage.prompt_tokens) for usage in present)
    completion_tokens = sum(
        _non_negative_int(usage.completion_tokens) for usage in present
    )
    total_tokens = sum(_non_negative_int(usage.total_tokens) for usage in present)
    estimated = any(usage.estimated for usage in present)
    source: TokenUsageSource = (
        TOKEN_USAGE_SOURCE_ESTIMATE if estimated else TOKEN_USAGE_SOURCE_PROVIDER
    )
    return CompletionTokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens or prompt_tokens + completion_tokens,
        source=source,
        estimated=estimated,
    )


def _provider_usage(response: Any) -> CompletionTokenUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return CompletionTokenUsage()

    prompt_tokens = _safe_int(getattr(usage, "prompt_tokens", None))
    completion_tokens = _safe_int(getattr(usage, "completion_tokens", None))
    total_tokens = _safe_int(getattr(usage, "total_tokens", None))
    if (
        total_tokens is None
        and prompt_tokens is not None
        and completion_tokens is not None
    ):
        total_tokens = prompt_tokens + completion_tokens
    return CompletionTokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        source=TOKEN_USAGE_SOURCE_PROVIDER,
        estimated=False,
    )


def _render_messages_for_counting(messages: Sequence[Mapping[str, Any]]) -> str:
    rendered: list[str] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        rendered.append(f"{role or 'message'}: {_render_content(content)}")
    return "\n".join(rendered)


def _render_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence) and not isinstance(content, (bytes, bytearray)):
        parts: list[str] = []
        for item in cast(Sequence[object], content):
            if isinstance(item, Mapping):
                text = cast(Mapping[str, object], item).get("text")
                if isinstance(text, str):
                    parts.append(text)
                    continue
            parts.append(_jsonish(item))
        return "\n".join(parts)
    return _jsonish(content)


def _jsonish(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _safe_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _non_negative_int(value: object) -> int:
    parsed = _safe_int(value)
    if parsed is None or parsed < 0:
        return 0
    return parsed


__all__ = [
    "CompletionTokenUsage",
    "TOKEN_USAGE_SOURCE_ESTIMATE",
    "TOKEN_USAGE_SOURCE_NONE",
    "TOKEN_USAGE_SOURCE_PROVIDER",
    "TokenUsageSource",
    "combine_token_usage",
    "completion_token_usage_from_response",
]
