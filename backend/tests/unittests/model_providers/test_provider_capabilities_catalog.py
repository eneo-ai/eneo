"""Catalog names served by ``GET /model-providers/capabilities/``.

The add-model wizard stores a picked catalog name as the model name, and
``resolve_model_route`` prefixes it with the provider type at call time. A
name that kept LiteLLM's own provider prefix was therefore routed as
``azure_ai/azure_ai/...`` (#1188).
"""

from collections import defaultdict
from typing import cast
from unittest.mock import MagicMock, patch

import litellm
import pytest

from eneo.model_providers.presentation.model_provider_router import (
    ModelCostInfo,
    ProviderCapabilities,
    get_provider_capabilities,
)
from eneo.tenants.provider_field_config import get_canonical_provider_type


async def _catalog(
    model_cost: dict[str, ModelCostInfo] | None = None,
) -> dict[str, ProviderCapabilities]:
    if model_cost is None:
        response = await get_provider_capabilities(_user=MagicMock())
    else:
        with patch("litellm.model_cost", model_cost):
            response = await get_provider_capabilities(_user=MagicMock())
    return cast(dict[str, ProviderCapabilities], response["providers"])


def _names(
    providers: dict[str, ProviderCapabilities], provider: str, mode: str
) -> list[str]:
    return [m["name"] for m in providers[provider]["models"][mode]]


async def test_catalog_names_leave_out_the_providers_own_prefix() -> None:
    providers = await _catalog(
        {
            "azure_ai/cohere-rerank-v4.0-fast": {
                "litellm_provider": "azure_ai",
                "mode": "rerank",
            },
            "mistral/codestral-2508": {"litellm_provider": "mistral", "mode": "chat"},
            "together_ai/Qwen/Qwen2.5-7B-Instruct-Turbo": {
                "litellm_provider": "together_ai",
                "mode": "chat",
            },
            # Upstream ids that merely contain a slash keep it.
            "accounts/fireworks/models/qwen3-embedding-4b": {
                "litellm_provider": "fireworks_ai",
                "mode": "embedding",
            },
            "rerank-v3.5": {"litellm_provider": "cohere", "mode": "rerank"},
            # OpenRouter's own id is "openrouter/auto": only one prefix goes.
            "openrouter/openrouter/auto": {
                "litellm_provider": "openrouter",
                "mode": "chat",
            },
        }
    )

    assert _names(providers, "azure_ai", "rerank") == ["cohere-rerank-v4.0-fast"]
    assert _names(providers, "mistral", "completion") == ["codestral-2508"]
    assert _names(providers, "together_ai", "completion") == [
        "Qwen/Qwen2.5-7B-Instruct-Turbo"
    ]
    assert _names(providers, "fireworks_ai", "embedding") == [
        "accounts/fireworks/models/qwen3-embedding-4b"
    ]
    assert _names(providers, "cohere", "rerank") == ["rerank-v3.5"]
    assert _names(providers, "openrouter", "completion") == ["openrouter/auto"]


@pytest.mark.parametrize("qualified_first", [True, False])
async def test_bare_and_qualified_entries_collapse_to_the_qualified_row(
    qualified_first: bool,
) -> None:
    bare: tuple[str, ModelCostInfo] = (
        "gemini-exp-1206",
        {"litellm_provider": "gemini", "mode": "chat", "max_input_tokens": 1048576},
    )
    qualified: tuple[str, ModelCostInfo] = (
        "gemini/gemini-exp-1206",
        {"litellm_provider": "gemini", "mode": "chat", "max_input_tokens": 2097152},
    )
    entries = [qualified, bare] if qualified_first else [bare, qualified]

    providers = await _catalog(dict(entries))

    models = providers["gemini"]["models"]["completion"]
    assert [m["name"] for m in models] == ["gemini-exp-1206"]
    assert models[0]["max_input_tokens"] == 2097152


async def test_the_raw_litellm_prefix_goes_too_under_the_canonical_provider() -> None:
    providers = await _catalog(
        {"vllm/x": {"litellm_provider": "vllm", "mode": "chat"}},
    )

    assert "vllm" not in providers
    assert _names(providers, "hosted_vllm", "completion") == ["x"]


async def test_only_a_whole_prefix_segment_is_stripped() -> None:
    providers = await _catalog(
        {
            "openai-whisper": {
                "litellm_provider": "openai",
                "mode": "audio_transcription",
            },
            "geminix/foo": {"litellm_provider": "gemini", "mode": "chat"},
        }
    )

    assert _names(providers, "openai", "transcription") == ["openai-whisper"]
    assert _names(providers, "gemini", "completion") == ["geminix/foo"]


@pytest.mark.parametrize(
    ("pricing_key", "provider", "litellm_mode"),
    [
        ("bedrock/*/1-month-commitment/cohere.command-text-v14", "bedrock", "chat"),
        (
            "bedrock/us-east-1/1-month-commitment/anthropic.claude-v2:1",
            "bedrock",
            "chat",
        ),
        (
            "bedrock/us-east-1/6-month-commitment/anthropic.claude-v2:1",
            "bedrock",
            "chat",
        ),
        ("1024-x-1024/gpt-image-1.5", "openai", "image_generation"),
        ("azure/hd/1024-x-1024/dall-e-3", "azure", "image_generation"),
    ],
)
async def test_litellm_pricing_templates_are_not_offered(
    pricing_key: str, provider: str, litellm_mode: str
) -> None:
    providers = await _catalog(
        {pricing_key: {"litellm_provider": provider, "mode": litellm_mode}},
    )

    # Providers with their own field definitions are listed even when empty.
    assert not any(
        models for data in providers.values() for models in data["models"].values()
    )


async def test_the_ids_that_pricing_templates_refer_to_stay() -> None:
    providers = await _catalog(
        {
            "bedrock/*/1-month-commitment/cohere.command-text-v14": {
                "litellm_provider": "bedrock",
                "mode": "chat",
            },
            "cohere.command-text-v14": {"litellm_provider": "bedrock", "mode": "chat"},
            "1024-x-1024/gpt-image-1.5": {
                "litellm_provider": "openai",
                "mode": "image_generation",
            },
            "gpt-image-1.5": {"litellm_provider": "openai", "mode": "image_generation"},
            # "8x7" is part of the id; only a "<W>-x-<H>/" segment is a size.
            "together_ai/mistralai/Mixtral-8x7B-Instruct-v0.1": {
                "litellm_provider": "together_ai",
                "mode": "chat",
            },
        }
    )

    assert _names(providers, "bedrock", "completion") == ["cohere.command-text-v14"]
    assert _names(providers, "openai", "image") == ["gpt-image-1.5"]
    assert _names(providers, "together_ai", "completion") == [
        "mistralai/Mixtral-8x7B-Instruct-v0.1"
    ]


async def test_no_bundled_catalog_name_is_one_of_litellms_prefixed_keys() -> None:
    model_cost = cast(dict[str, ModelCostInfo], getattr(litellm, "model_cost"))

    # Keys LiteLLM lists under a provider with that provider's own prefix, raw
    # ("vllm/...") or canonical ("hosted_vllm/..."), and what they strip to.
    prefixed_keys: dict[str, set[str]] = defaultdict(set)
    stripped: set[tuple[str, str]] = set()
    for key, info in model_cost.items():
        raw_provider = info.get("litellm_provider", "")
        if not raw_provider:
            continue
        provider = get_canonical_provider_type(raw_provider)
        for prefix in (f"{provider}/", f"{raw_provider}/"):
            if key.startswith(prefix):
                prefixed_keys[provider].add(key)
                stripped.add((provider, key.removeprefix(prefix)))
                break

    providers = await _catalog()
    offered = {
        (provider, model["name"])
        for provider, data in providers.items()
        for models in data["models"].values()
        for model in models
    }

    # The bundled map must exercise the strip, or the check below is vacuous.
    assert offered & stripped

    for provider, name in offered:
        # The prefixed key itself is only a valid name when the upstream id
        # repeats the prefix ("openrouter/openrouter/auto" -> "openrouter/auto").
        if name in prefixed_keys[provider]:
            assert f"{provider}/{name}" in model_cost, (provider, name)
