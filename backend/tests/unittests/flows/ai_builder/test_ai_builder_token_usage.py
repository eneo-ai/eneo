from __future__ import annotations

from types import SimpleNamespace

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
    monkeypatch,
) -> None:
    def fake_count_tokens(text: str, model_name: str = "") -> int:
        return len(text)

    monkeypatch.setattr(ai_builder_token_usage, "count_tokens", fake_count_tokens)

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
    assert usage.completion_tokens == len("done")
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
