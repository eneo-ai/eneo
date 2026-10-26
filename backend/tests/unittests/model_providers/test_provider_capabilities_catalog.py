"""Catalog names served by ``GET /model-providers/capabilities/``.

The add-model wizard stores a picked catalog name as the model name, and
``resolve_model_route`` prefixes it with the provider type at call time. A
name that kept LiteLLM's own provider prefix was therefore routed as
``azure_ai/azure_ai/...`` (#1188).
"""

from typing import Any, cast
from unittest.mock import MagicMock, patch

import litellm
import pytest

from eneo.model_providers.domain.model_route import resolve_model_route
from eneo.model_providers.presentation.model_provider_router import (
    get_provider_capabilities,
)


async def _catalog(model_cost: dict[str, dict[str, Any]] | None = None) -> Any:
    if model_cost is None:
        response = await get_provider_capabilities(_user=MagicMock())
    else:
        with patch("litellm.model_cost", model_cost):
            response = await get_provider_capabilities(_user=MagicMock())
    return cast(dict[str, Any], response)["providers"]


def _names(providers: Any, provider: str, mode: str) -> list[str]:
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
    bare = (
        "gemini-exp-1206",
        {"litellm_provider": "gemini", "mode": "chat", "max_input_tokens": 1048576},
    )
    qualified = (
        "gemini/gemini-exp-1206",
        {"litellm_provider": "gemini", "mode": "chat", "max_input_tokens": 2097152},
    )
    entries = [qualified, bare] if qualified_first else [bare, qualified]

    providers = await _catalog(dict(entries))

    models = providers["gemini"]["models"]["completion"]
    assert [m["name"] for m in models] == ["gemini-exp-1206"]
    assert models[0]["max_input_tokens"] == 2097152


async def test_no_bundled_catalog_name_repeats_its_providers_prefix() -> None:
    model_cost = cast(dict[str, Any], getattr(litellm, "model_cost"))
    providers = await _catalog()

    for provider, data in providers.items():
        for models in data["models"].values():
            for model in models:
                name = model["name"]
                route = resolve_model_route(provider_type=provider, model_name=name)
                # A repeated prefix is only right when the upstream id has it.
                assert route in model_cost or not name.startswith(f"{provider}/"), route
