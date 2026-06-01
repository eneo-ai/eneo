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


def test_unknown_image_model_dropped() -> None:
    with _patch_cost_map({}):
        result = model_provider_service._enrich_with_litellm_metadata(
            "dall-e-99", "openai"
        )
    assert result is None
