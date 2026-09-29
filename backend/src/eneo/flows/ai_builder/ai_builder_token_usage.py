from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from eneo.tokens.token_utils import count_message_tokens

TokenUsageSource = Literal["provider", "litellm_estimate", "none"]

TOKEN_USAGE_SOURCE_PROVIDER: TokenUsageSource = "provider"
TOKEN_USAGE_SOURCE_ESTIMATE: TokenUsageSource = "litellm_estimate"
TOKEN_USAGE_SOURCE_NONE: TokenUsageSource = "none"

# A provider count above this is malformed: it reads as unreported, like a
# negative one, so no consumer has to bound the digits.
MAX_PROVIDER_TOKEN_COUNT = 10**12


@dataclass(frozen=True, slots=True)
class CompletionTokenUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    source: TokenUsageSource = TOKEN_USAGE_SOURCE_NONE
    estimated: bool = False
    reasoning_tokens: int | None = None

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
    completion_text: str | None = None,
    completion_messages: Sequence[Mapping[str, Any]] | None = None,
) -> CompletionTokenUsage:
    """Extract provider usage or estimate it at the LLM boundary.

    The rest of AI Builder should not know provider response shapes. Keeping
    the fallback at the call boundary preserves the committed-turn telemetry
    contract while making missing `response.usage` visible to the UI.
    """

    provider_usage = provider_token_usage(_field(response, "usage"))
    if provider_usage is not None:
        return provider_usage

    prompt_tokens = count_message_tokens(
        [dict(message) for message in messages], model_name
    )
    normalized_completion_messages = completion_messages
    if normalized_completion_messages is None:
        normalized_completion_messages = (
            [{"role": "assistant", "content": completion_text or ""}]
            if completion_text
            else []
        )
    completion_tokens = count_message_tokens(
        [dict(message) for message in normalized_completion_messages], model_name
    )
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


def provider_token_usage(usage: Any) -> CompletionTokenUsage | None:
    """Read a provider usage block (SDK object or mapping); None when it has no tokens."""

    prompt_tokens = _token_count(_field(usage, "prompt_tokens"))
    completion_tokens = _token_count(_field(usage, "completion_tokens"))
    total_tokens = _token_count(_field(usage, "total_tokens"))
    if (
        total_tokens is None
        and prompt_tokens is not None
        and completion_tokens is not None
    ):
        total_tokens = prompt_tokens + completion_tokens
    reasoning_tokens = _token_count(_field(usage, "reasoning_tokens"))
    if reasoning_tokens is None:
        reasoning_tokens = _token_count(
            _field(_field(usage, "completion_tokens_details"), "reasoning_tokens")
        )
    provider_usage = CompletionTokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        source=TOKEN_USAGE_SOURCE_PROVIDER,
        reasoning_tokens=reasoning_tokens,
    )
    return provider_usage if provider_usage.has_tokens else None


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value).get(name)
    return getattr(value, name, None)


def _token_count(value: object) -> int | None:
    """A provider count is an integer in [0, MAX_PROVIDER_TOKEN_COUNT]; else unreported."""

    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= MAX_PROVIDER_TOKEN_COUNT
    ):
        return value
    return None


def _non_negative_int(value: object) -> int:
    return _token_count(value) or 0


__all__ = [
    "CompletionTokenUsage",
    "MAX_PROVIDER_TOKEN_COUNT",
    "TOKEN_USAGE_SOURCE_ESTIMATE",
    "TOKEN_USAGE_SOURCE_NONE",
    "TOKEN_USAGE_SOURCE_PROVIDER",
    "TokenUsageSource",
    "combine_token_usage",
    "completion_token_usage_from_response",
    "provider_token_usage",
]
