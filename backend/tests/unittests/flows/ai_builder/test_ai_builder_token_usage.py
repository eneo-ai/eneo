from __future__ import annotations

from types import SimpleNamespace

import pytest

from eneo.flows.ai_builder import ai_builder_token_usage
from eneo.flows.ai_builder.ai_builder_token_usage import (
    TOKEN_USAGE_SOURCE_ESTIMATE,
    TOKEN_USAGE_SOURCE_PROVIDER,
    completion_token_usage_from_response,
)


def _response_with_usage(
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    )


def test_completion_token_usage_prefers_provider_usage() -> None:
    usage = completion_token_usage_from_response(
        _response_with_usage(
            prompt_tokens=12,
            completion_tokens=7,
            total_tokens=19,
        ),
        model_name="openai/gpt-5.4",
        messages=[{"role": "user", "content": "ignored when provider usage exists"}],
        completion_text="also ignored",
    )

    assert usage.prompt_tokens == 12
    assert usage.completion_tokens == 7
    assert usage.total_tokens == 19
    assert usage.source == TOKEN_USAGE_SOURCE_PROVIDER
    assert usage.estimated is False


def test_completion_token_usage_estimates_when_provider_usage_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_count_message_tokens(
        messages: list[dict[str, object]], model_name: str = ""
    ) -> int:
        return len(messages)

    monkeypatch.setattr(
        ai_builder_token_usage, "count_message_tokens", fake_count_message_tokens
    )

    usage = completion_token_usage_from_response(
        SimpleNamespace(usage=None),
        model_name="openai/gpt-5.4",
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        ],
        completion_text="done",
    )

    assert usage.prompt_tokens > 0
    assert usage.completion_tokens == 1
    assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens
    assert usage.source == TOKEN_USAGE_SOURCE_ESTIMATE
    assert usage.estimated is True


def test_completion_token_usage_derives_missing_provider_total() -> None:
    usage = completion_token_usage_from_response(
        _response_with_usage(
            prompt_tokens=12,
            completion_tokens=7,
            total_tokens=None,
        ),
        model_name="openai/gpt-5.4",
        messages=[],
        completion_text="",
    )

    assert usage.prompt_tokens == 12
    assert usage.completion_tokens == 7
    assert usage.total_tokens == 19
    assert usage.source == TOKEN_USAGE_SOURCE_PROVIDER
    assert usage.estimated is False


def test_completion_token_usage_fallback_counts_normalized_tool_call_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counted_messages: list[list[dict[str, object]]] = []

    def fake_count_message_tokens(
        messages: list[dict[str, object]], model_name: str = ""
    ) -> int:
        counted_messages.append(messages)
        serialized = str(messages)
        return serialized.count("unique-tool-arguments") * 100 + len(messages)

    monkeypatch.setattr(
        ai_builder_token_usage,
        "count_message_tokens",
        fake_count_message_tokens,
    )
    completion_message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-usage",
                "type": "function",
                "function": {
                    "name": "propose_flow",
                    "arguments": "unique-tool-arguments",
                },
            }
        ],
    }

    usage = completion_token_usage_from_response(
        SimpleNamespace(usage=None),
        model_name="openai/gpt-5.4",
        messages=[{"role": "user", "content": "request"}],
        completion_messages=[completion_message],
    )

    assert usage.prompt_tokens == 1
    assert usage.completion_tokens == 101
    assert counted_messages == [
        [{"role": "user", "content": "request"}],
        [completion_message],
    ]
