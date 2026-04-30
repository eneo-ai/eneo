"""Unit tests for the live-listing metadata enrichment helper."""

from typing import Any
from unittest.mock import patch

import pytest

from intric.model_providers.domain import model_provider_service


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


def test_enriches_embedding_model() -> None:
    fake = {
        "text-embedding-3-large": {
            "litellm_provider": "openai",
            "mode": "embedding",
            "max_input_tokens": 8191,
            "output_vector_size": 3072,
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


def test_filters_image_and_tts_modes() -> None:
    fake = {
        "dall-e-3": {"litellm_provider": "openai", "mode": "image_generation"},
        "tts-1": {"litellm_provider": "openai", "mode": "audio_speech"},
        "omni-moderation-latest": {
            "litellm_provider": "openai",
            "mode": "moderation",
        },
    }
    with _patch_cost_map(fake):
        assert (
            model_provider_service._enrich_with_litellm_metadata("dall-e-3", "openai")
            is None
        )
        assert (
            model_provider_service._enrich_with_litellm_metadata("tts-1", "openai")
            is None
        )


def test_unknown_anthropic_model_defaults_to_completion() -> None:
    """Anthropic's /v1/models only ever returns chat models, so unknown names
    fall through as completion. This keeps newly-released models reachable."""
    with _patch_cost_map({}):
        result = model_provider_service._enrich_with_litellm_metadata(
            "claude-opus-4-99", "anthropic"
        )
    assert result == {"name": "claude-opus-4-99", "mode": "completion"}


def test_unknown_openai_gpt_model_defaults_to_completion() -> None:
    with _patch_cost_map({}):
        result = model_provider_service._enrich_with_litellm_metadata(
            "gpt-9-future", "openai"
        )
    assert result == {"name": "gpt-9-future", "mode": "completion"}


def test_unknown_openai_whisper_defaults_to_transcription() -> None:
    with _patch_cost_map({}):
        result = model_provider_service._enrich_with_litellm_metadata(
            "whisper-2", "openai"
        )
    assert result == {"name": "whisper-2", "mode": "transcription"}


def test_unknown_openai_image_model_dropped() -> None:
    with _patch_cost_map({}):
        result = model_provider_service._enrich_with_litellm_metadata(
            "dall-e-99", "openai"
        )
    assert result is None


def test_unknown_arbitrary_model_dropped() -> None:
    """For unknown providers and arbitrary names, we don't guess — better to
    drop than to pollute the wrong mode picker."""
    with _patch_cost_map({}):
        result = model_provider_service._enrich_with_litellm_metadata(
            "mystery-model-xyz", "vllm"
        )
    assert result is None
