"""
Tests for the deprecation lookup utility that checks LiteLLM's model_cost
for deprecation dates on imported models.
"""

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from intric.ai_models.deprecation_lookup import (
    get_litellm_deprecation_date,
    is_model_deprecated,
    is_model_effectively_deprecated,
)

# Past and future dates are derived from today so the "is it deprecated yet?"
# tests stay stable regardless of when CI runs. Using a hardcoded calendar
# date (we had 2026-12-01 here previously) silently turns the future case
# into a past case the moment the calendar ticks past it, then the test
# starts failing in CI with no code change.
_PAST_DATE = (date.today() - timedelta(days=365)).isoformat()
_FUTURE_DATE = (date.today() + timedelta(days=365)).isoformat()


@pytest.fixture
def mock_model_cost():
    """Sample litellm.model_cost entries for testing."""
    return {
        "gpt-4-0613": {
            "litellm_provider": "openai",
            "mode": "chat",
            "deprecation_date": _PAST_DATE,
        },
        "openai/gpt-4o-2024-05-13": {
            "litellm_provider": "openai",
            "mode": "chat",
            "deprecation_date": _FUTURE_DATE,
        },
        "anthropic/claude-3-haiku-20240307": {
            "litellm_provider": "anthropic",
            "mode": "chat",
        },
        "openai/gpt-4o": {
            "litellm_provider": "openai",
            "mode": "chat",
        },
    }


class TestGetLitellmDeprecationDate:
    def test_lookup_with_provider_type_prefix(self, mock_model_cost):
        """Should find model using provider_type/model_name key."""
        with patch("litellm.model_cost", mock_model_cost):
            result = get_litellm_deprecation_date("gpt-4o-2024-05-13", "openai")
            assert result == _FUTURE_DATE

    def test_lookup_bare_model_name(self, mock_model_cost):
        """Should fall back to bare model name when prefixed key not found."""
        with patch("litellm.model_cost", mock_model_cost):
            result = get_litellm_deprecation_date("gpt-4-0613")
            assert result == _PAST_DATE

    def test_lookup_bare_name_when_no_provider_type(self, mock_model_cost):
        """Should use bare name when provider_type is None."""
        with patch("litellm.model_cost", mock_model_cost):
            result = get_litellm_deprecation_date("gpt-4-0613", None)
            assert result == _PAST_DATE

    def test_model_without_deprecation_date(self, mock_model_cost):
        """Should return None when model exists but has no deprecation_date."""
        with patch("litellm.model_cost", mock_model_cost):
            result = get_litellm_deprecation_date(
                "claude-3-haiku-20240307", "anthropic"
            )
            assert result is None

    def test_model_not_in_cost_map(self, mock_model_cost):
        """Should return None when model is not in litellm.model_cost at all."""
        with patch("litellm.model_cost", mock_model_cost):
            result = get_litellm_deprecation_date("nonexistent-model", "openai")
            assert result is None

    def test_self_hosted_model_not_found(self, mock_model_cost):
        """Self-hosted models (hosted_vllm) won't be in model_cost — should return None."""
        with patch("litellm.model_cost", mock_model_cost):
            result = get_litellm_deprecation_date(
                "meta-llama/Meta-Llama-3-70B-Instruct", "hosted_vllm"
            )
            assert result is None

    def test_prefixed_key_takes_priority_over_bare(self, mock_model_cost):
        """When both prefixed and bare keys exist, prefixed should be used."""
        cost = {
            "gpt-4-0613": {
                "deprecation_date": "2025-01-01",
            },
            "openai/gpt-4-0613": {
                "deprecation_date": "2025-06-13",
            },
        }
        with patch("litellm.model_cost", cost):
            result = get_litellm_deprecation_date("gpt-4-0613", "openai")
            assert result == "2025-06-13"


class TestIsModelDeprecated:
    def test_deprecated_when_date_in_past(self, mock_model_cost):
        """Model with deprecation_date in the past should be deprecated."""
        with patch("litellm.model_cost", mock_model_cost):
            result = is_model_deprecated("gpt-4-0613")
            assert result is True

    def test_not_deprecated_when_date_in_future(self, mock_model_cost):
        """Model with deprecation_date in the future should not be deprecated."""
        with patch("litellm.model_cost", mock_model_cost):
            result = is_model_deprecated("gpt-4o-2024-05-13", "openai")
            assert result is False

    def test_not_deprecated_when_no_date(self, mock_model_cost):
        """Model without deprecation_date should not be deprecated."""
        with patch("litellm.model_cost", mock_model_cost):
            result = is_model_deprecated("gpt-4o", "openai")
            assert result is False

    def test_not_deprecated_when_not_found(self, mock_model_cost):
        """Model not in model_cost should not be deprecated."""
        with patch("litellm.model_cost", mock_model_cost):
            result = is_model_deprecated("nonexistent", "openai")
            assert result is False


class TestIsModelEffectivelyDeprecated:
    def test_manual_deprecation_wins_without_litellm_date(self, mock_model_cost):
        with patch("litellm.model_cost", mock_model_cost):
            result = is_model_effectively_deprecated(
                "nonexistent",
                "openai",
                manually_deprecated=True,
            )

        assert result is True

    def test_litellm_deprecation_counts_when_manual_flag_is_false(
        self, mock_model_cost
    ):
        with patch("litellm.model_cost", mock_model_cost):
            result = is_model_effectively_deprecated(
                "gpt-4-0613",
                manually_deprecated=False,
            )

        assert result is True
