"""Unit tests for the shared LiteLLM defaults resolver.

The resolver is the single source of truth for both the interactive
``/model-defaults/`` endpoint and the cost-backfill migration, so the test
matrix needs to cover the cases where the two used to disagree:

  - bare-name vs. provider-prefixed entries
  - same model under multiple providers (must not silently pick one)
  - operator-set ``litellm_model_name`` overriding display name

If these change, the migration and the wizard's "Lookup defaults" button
will start writing different numbers for the same model — exactly the
class of bug Fas 1 was created to fix.
"""

from __future__ import annotations

from typing import Any

from intric.model_providers.domain.model_defaults_lookup import (
    is_ambiguous,
    resolve_model_defaults,
)

_AZURE_GPT4O: dict[str, Any] = {
    "litellm_provider": "azure",
    "input_cost_per_token": 0.000003,
    "output_cost_per_token": 0.000010,
}

_OPENAI_GPT4O: dict[str, Any] = {
    "litellm_provider": "openai",
    "input_cost_per_token": 0.000005,
    "output_cost_per_token": 0.000015,
}

_BARE_EMBEDDING: dict[str, Any] = {
    "litellm_provider": "openai",
    "mode": "embedding",
    "input_cost_per_token": 0.0000001,
}


def test_prefers_provider_prefixed_entry_when_provider_known() -> None:
    cost = {"gpt-4o": _OPENAI_GPT4O, "azure/gpt-4o": _AZURE_GPT4O}
    result = resolve_model_defaults(cost, "gpt-4o", "azure")
    assert result is _AZURE_GPT4O


def test_falls_back_to_bare_name_when_provider_prefix_missing() -> None:
    """OpenAI embeddings only live under the bare key — must still resolve."""
    cost = {"text-embedding-3-large": _BARE_EMBEDDING}
    result = resolve_model_defaults(cost, "text-embedding-3-large", "openai")
    assert result is _BARE_EMBEDDING


def test_skips_when_ambiguous_without_provider_context() -> None:
    """Same name under two providers + no provider hint → must return None.

    Picking alphabetically used to silently overwrite billing columns; the
    contract now is that the admin disambiguates manually."""
    cost = {"openai/gpt-4o": _OPENAI_GPT4O, "azure/gpt-4o": _AZURE_GPT4O}
    result = resolve_model_defaults(cost, "gpt-4o", None)
    assert result is None


def test_accepts_unambiguous_prefix_match_without_provider_context() -> None:
    """Single prefixed match is safe to pick when there's no bare entry."""
    cost = {"openai/gpt-4o": _OPENAI_GPT4O}
    result = resolve_model_defaults(cost, "gpt-4o", None)
    assert result is _OPENAI_GPT4O


def test_candidate_list_tries_in_order() -> None:
    """First candidate (operator override) wins over display name."""
    cost = {
        "operator-override-name": {"input_cost_per_token": 0.1},
        "display-name": {"input_cost_per_token": 0.2},
    }
    result = resolve_model_defaults(
        cost, ["operator-override-name", "display-name"], None
    )
    assert result == {"input_cost_per_token": 0.1}


def test_empty_candidates_return_none() -> None:
    assert resolve_model_defaults({"x": {}}, [], None) is None
    assert resolve_model_defaults({"x": {}}, [None], None) is None


def test_returns_none_when_nothing_matches() -> None:
    cost = {"some-other-model": {}}
    assert resolve_model_defaults(cost, "unknown", "openai") is None
    assert resolve_model_defaults(cost, "unknown", None) is None


def test_is_ambiguous_detects_multi_provider_names() -> None:
    cost = {"openai/gpt-4o": _OPENAI_GPT4O, "azure/gpt-4o": _AZURE_GPT4O}
    assert is_ambiguous(cost, "gpt-4o") is True


def test_is_ambiguous_false_when_bare_entry_exists() -> None:
    """Bare entry counts as canonical — no ambiguity even if prefixed copies
    exist."""
    cost = {
        "gpt-4o": _OPENAI_GPT4O,
        "openai/gpt-4o": _OPENAI_GPT4O,
        "azure/gpt-4o": _AZURE_GPT4O,
    }
    assert is_ambiguous(cost, "gpt-4o") is False


def test_is_ambiguous_false_for_single_prefix() -> None:
    cost = {"openai/gpt-4o": _OPENAI_GPT4O}
    assert is_ambiguous(cost, "gpt-4o") is False


def test_is_ambiguous_false_for_unknown_name() -> None:
    assert is_ambiguous({"openai/gpt-4o": _OPENAI_GPT4O}, "claude-x") is False
    assert is_ambiguous({}, "") is False
    assert is_ambiguous({}, None) is False
