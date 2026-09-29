from __future__ import annotations

from types import SimpleNamespace

import pytest

from eneo.flows.ai_builder import ai_builder_token_usage
from eneo.flows.ai_builder.ai_builder_litellm_completion import (
    normalize_litellm_completion_response,
)
from eneo.flows.ai_builder.ai_builder_token_usage import (
    MAX_PROVIDER_TOKEN_COUNT,
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


def _reasoning_usage(*, reasoning_tokens: int | None) -> SimpleNamespace:
    return SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=40,
            total_tokens=140,
            completion_tokens_details=(
                None
                if reasoning_tokens is None
                else SimpleNamespace(reasoning_tokens=reasoning_tokens)
            ),
        )
    )


def test_provider_reasoning_tokens_survive_the_completion_normalization() -> None:
    normalized = normalize_litellm_completion_response(
        _reasoning_usage(reasoning_tokens=25)
    )

    usage = completion_token_usage_from_response(
        normalized, model_name="openai/gpt-5.4", messages=[]
    )

    assert usage.reasoning_tokens == 25
    assert usage.source == TOKEN_USAGE_SOURCE_PROVIDER


def test_provider_reasoning_tokens_are_read_from_a_raw_sdk_response() -> None:
    usage = completion_token_usage_from_response(
        _reasoning_usage(reasoning_tokens=25), model_name="openai/gpt-5.4", messages=[]
    )

    assert usage.reasoning_tokens == 25


def test_unreported_reasoning_tokens_stay_unknown_not_zero() -> None:
    usage = completion_token_usage_from_response(
        normalize_litellm_completion_response(_reasoning_usage(reasoning_tokens=None)),
        model_name="openai/gpt-5.4",
        messages=[],
    )

    assert usage.total_tokens == 140
    assert usage.reasoning_tokens is None


def _response_with_counts(**counts: int) -> SimpleNamespace:
    return SimpleNamespace(usage=SimpleNamespace(**counts))


def test_a_negative_provider_count_is_reported_as_unknown_not_kept() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=-4,
            completion_tokens=6,
            total_tokens=-1,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=-2),
        )
    )

    for source in (response, normalize_litellm_completion_response(response)):
        usage = completion_token_usage_from_response(
            source, model_name="openai/gpt-5.4", messages=[]
        )

        assert usage.source == TOKEN_USAGE_SOURCE_PROVIDER
        assert usage.prompt_tokens is None
        assert usage.completion_tokens == 6
        assert usage.total_tokens is None
        assert usage.reasoning_tokens is None


def test_a_provider_block_of_only_negative_counts_falls_back_to_the_estimate() -> None:
    usage = completion_token_usage_from_response(
        _response_with_counts(prompt_tokens=-4, completion_tokens=-6),
        model_name="openai/gpt-5.4",
        messages=[{"role": "user", "content": "Build a flow"}],
        completion_text="Done",
    )

    assert usage.source == TOKEN_USAGE_SOURCE_ESTIMATE
    assert usage.estimated is True
    assert usage.prompt_tokens is not None and usage.prompt_tokens > 0
    assert usage.completion_tokens is not None and usage.completion_tokens > 0


@pytest.mark.parametrize(
    "oversized",
    [
        pytest.param(10**30, id="31-digits"),
        pytest.param(10**200, id="201-digits"),
        pytest.param(10**4300, id="4301-digits"),
    ],
)
def test_a_count_above_the_bound_is_reported_as_unknown_not_kept(
    oversized: int,
) -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=oversized,
            completion_tokens=6,
            total_tokens=oversized,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=oversized),
        )
    )

    usage = completion_token_usage_from_response(
        response, model_name="openai/gpt-5.4", messages=[]
    )

    assert usage.source == TOKEN_USAGE_SOURCE_PROVIDER
    assert (usage.prompt_tokens, usage.completion_tokens) == (None, 6)
    assert (usage.total_tokens, usage.reasoning_tokens) == (None, None)


def test_a_count_is_kept_up_to_the_bound_and_dropped_beyond_it() -> None:
    at_bound = completion_token_usage_from_response(
        _response_with_counts(prompt_tokens=MAX_PROVIDER_TOKEN_COUNT),
        model_name="openai/gpt-5.4",
        messages=[],
    )
    beyond = completion_token_usage_from_response(
        _response_with_counts(prompt_tokens=MAX_PROVIDER_TOKEN_COUNT + 1),
        model_name="openai/gpt-5.4",
        messages=[{"role": "user", "content": "Build a flow"}],
    )

    assert at_bound.prompt_tokens == MAX_PROVIDER_TOKEN_COUNT
    assert at_bound.source == TOKEN_USAGE_SOURCE_PROVIDER
    assert beyond.source == TOKEN_USAGE_SOURCE_ESTIMATE


def test_a_provider_block_of_only_oversized_counts_falls_back_to_the_estimate() -> None:
    usage = completion_token_usage_from_response(
        _response_with_counts(prompt_tokens=10**200, completion_tokens=10**30),
        model_name="openai/gpt-5.4",
        messages=[{"role": "user", "content": "Build a flow"}],
        completion_text="Done",
    )

    assert usage.source == TOKEN_USAGE_SOURCE_ESTIMATE
    assert usage.prompt_tokens is not None and usage.prompt_tokens < 10**6


def test_provider_usage_is_read_from_a_mapping_response() -> None:
    usage = completion_token_usage_from_response(
        {
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 7,
                "completion_tokens_details": {"reasoning_tokens": 3},
            }
        },
        model_name="openai/gpt-5.4",
        messages=[],
    )

    assert usage.source == TOKEN_USAGE_SOURCE_PROVIDER
    assert (usage.prompt_tokens, usage.completion_tokens) == (12, 7)
    assert (usage.total_tokens, usage.reasoning_tokens) == (19, 3)
