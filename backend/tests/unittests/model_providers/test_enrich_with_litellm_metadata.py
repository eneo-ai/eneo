"""Unit tests for the live-listing metadata enrichment helper."""

from typing import Any
from unittest.mock import patch

import pytest

from eneo.model_providers.domain import model_provider_service


def _patch_cost_map(fake: dict[str, dict[str, Any]]):
    """Helper: patch litellm.model_cost for the duration of a test."""
    return patch("litellm.model_cost", fake)


def test_enriches_known_completion_model() -> None:
    fake = {
        "claude-opus-4-7": {
            "litellm_provider": "anthropic",
            "mode": "chat",
            "max_input_tokens": 200000,
            "max_output_tokens": 8000,
            "supports_vision": True,
            "supports_function_calling": True,
            "supports_reasoning": True,
            "input_cost_per_token": 0.000015,
            "output_cost_per_token": 0.000075,
        }
    }
    with _patch_cost_map(fake):
        result = model_provider_service._enrich_with_litellm_metadata(
            "claude-opus-4-7", "anthropic"
        )
    assert result == {
        "name": "claude-opus-4-7",
        "mode": "completion",
        "max_input_tokens": 200000,
        "max_output_tokens": 8000,
        "supports_vision": True,
        "supports_function_calling": True,
        "supports_reasoning": True,
        "input_cost_per_token": 0.000015,
        "output_cost_per_token": 0.000075,
    }


def test_enriches_via_provider_prefix_lookup() -> None:
    """OpenAI-style names sometimes only exist as `openai/<name>` in cost map."""
    fake = {
        "openai/gpt-4o": {
            "litellm_provider": "openai",
            "mode": "chat",
            "max_input_tokens": 128000,
            "max_output_tokens": 16000,
            "supports_vision": True,
            "supports_function_calling": True,
            "supports_reasoning": False,
        }
    }
    with _patch_cost_map(fake):
        result = model_provider_service._enrich_with_litellm_metadata(
            "gpt-4o", "openai"
        )
    assert result is not None
    assert result["mode"] == "completion"
    assert result["max_input_tokens"] == 128000


def test_prefers_provider_prefixed_entry_over_bare() -> None:
    """When both `{provider}/{name}` and bare `{name}` exist with different
    values, the prefixed row must win — the same rule the `/model-defaults/`
    endpoint applies (see test_model_defaults_lookup). This used to diverge:
    a local candidate list here tried the bare key first.
    """
    fake = {
        "gpt-4o": {
            "litellm_provider": "openai",
            "mode": "chat",
            "max_input_tokens": 128000,
            "input_cost_per_token": 0.000005,
        },
        "azure/gpt-4o": {
            "litellm_provider": "azure",
            "mode": "chat",
            "max_input_tokens": 100000,
            "input_cost_per_token": 0.000003,
        },
    }
    with _patch_cost_map(fake):
        azure = model_provider_service._enrich_with_litellm_metadata("gpt-4o", "azure")
        openai = model_provider_service._enrich_with_litellm_metadata(
            "gpt-4o", "openai"
        )
    assert azure is not None and openai is not None
    assert azure["max_input_tokens"] == 100000
    assert azure["input_cost_per_token"] == 0.000003
    # No `openai/gpt-4o` entry in the map → the bare row is the right match.
    assert openai["max_input_tokens"] == 128000


def test_prefers_gateway_metadata_for_nested_model_id() -> None:
    """Gateway providers prefix model IDs that already contain an upstream
    provider segment. The gateway-specific row must win without changing the
    nested model ID returned to the caller.
    """
    fake = {
        "deepseek/deepseek-chat": {
            "litellm_provider": "deepseek",
            "mode": "chat",
            "max_input_tokens": 131072,
            "input_cost_per_token": 0.00000028,
        },
        "openrouter/deepseek/deepseek-chat": {
            "litellm_provider": "openrouter",
            "mode": "chat",
            "max_input_tokens": 65536,
            "input_cost_per_token": 0.00000014,
        },
    }
    with _patch_cost_map(fake):
        result = model_provider_service._enrich_with_litellm_metadata(
            "deepseek/deepseek-chat", "openrouter"
        )

    assert result is not None
    assert result["name"] == "deepseek/deepseek-chat"
    assert result["max_input_tokens"] == 65536
    assert result["input_cost_per_token"] == 0.00000014


def test_enriches_embedding_model() -> None:
    fake = {
        "text-embedding-3-large": {
            "litellm_provider": "openai",
            "mode": "embedding",
            "max_input_tokens": 8191,
            "output_vector_size": 3072,
            "input_cost_per_token": 0.00000013,
            "output_cost_per_token": None,
        }
    }
    with _patch_cost_map(fake):
        result = model_provider_service._enrich_with_litellm_metadata(
            "text-embedding-3-large", "openai"
        )
    assert result == {
        "name": "text-embedding-3-large",
        "mode": "embedding",
        "max_input_tokens": 8191,
        "output_vector_size": 3072,
        "input_cost_per_token": 0.00000013,
        "output_cost_per_token": None,
    }


@pytest.mark.parametrize(
    "name",
    [
        "gpt-4o-realtime-preview",
        "gpt-audio-mini",
        "whisper-1-search-preview",
        "claude-3-5-sonnet-diarize",
    ],
)
def test_filters_realtime_audio_search_diarize(name: str) -> None:
    fake = {name: {"litellm_provider": "openai", "mode": "chat"}}
    with _patch_cost_map(fake):
        assert (
            model_provider_service._enrich_with_litellm_metadata(name, "openai") is None
        )


@pytest.mark.parametrize(
    "name",
    ["gpt-4o-latest", "claude-3-5-sonnet-latest"],
)
def test_filters_latest_aliases(name: str) -> None:
    fake = {name: {"litellm_provider": "openai", "mode": "chat"}}
    with _patch_cost_map(fake):
        assert (
            model_provider_service._enrich_with_litellm_metadata(name, "openai") is None
        )


def test_filters_tts_modes_and_surfaces_image_generation() -> None:
    fake = {
        "dall-e-3": {
            "litellm_provider": "openai",
            "mode": "image_generation",
            "input_cost_per_image": 0.04,
        },
        "tts-1": {"litellm_provider": "openai", "mode": "audio_speech"},
        "omni-moderation-latest": {
            "litellm_provider": "openai",
            "mode": "moderation",
        },
    }
    with _patch_cost_map(fake):
        assert model_provider_service._enrich_with_litellm_metadata(
            "dall-e-3", "openai"
        ) == {"name": "dall-e-3", "mode": "image", "cost_per_image": 0.04}
        assert (
            model_provider_service._enrich_with_litellm_metadata("tts-1", "openai")
            is None
        )


def test_unknown_name_defaults_to_completion() -> None:
    """Live-listed names that aren't in the cost map default to completion —
    if the provider served it on /v1/models we trust it's a real text model."""
    with _patch_cost_map({}):
        result = model_provider_service._enrich_with_litellm_metadata(
            "future-model-1", "openai"
        )
    assert result == {"name": "future-model-1", "mode": "completion"}


def test_unknown_whisper_inferred_as_transcription() -> None:
    with _patch_cost_map({}):
        result = model_provider_service._enrich_with_litellm_metadata(
            "whisper-2", "openai"
        )
    assert result == {"name": "whisper-2", "mode": "transcription"}


def test_unknown_embedding_inferred_as_embedding() -> None:
    with _patch_cost_map({}):
        result = model_provider_service._enrich_with_litellm_metadata(
            "future-embedding-1", "openai"
        )
    assert result == {"name": "future-embedding-1", "mode": "embedding"}


def test_unknown_image_model_inferred_as_image() -> None:
    with _patch_cost_map({}):
        result = model_provider_service._enrich_with_litellm_metadata(
            "dall-e-99", "openai"
        )
    assert result == {"name": "dall-e-99", "mode": "image"}
