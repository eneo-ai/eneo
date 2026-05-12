"""Unit tests for the LiteLLM lookup helper in 20260501_backfill_model_costs.

The migration's _lookup decides which entry from litellm.model_cost a row should
be backfilled with. The earlier version sorted prefixes alphabetically, so a
tenant whose `gpt-4o` was served via Azure could silently get OpenAI's prices.
These tests pin down the current rules.
"""

import importlib.util
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(scope="module")
def migration_module():
    """Load the alembic migration as a module so we can call _lookup directly."""
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "20260501_backfill_model_costs.py"
    )
    spec = importlib.util.spec_from_file_location("backfill_model_costs", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cost_map() -> dict[str, dict[str, Any]]:
    return {
        "gpt-4o": {"input_cost_per_token": 0.000005, "output_cost_per_token": 0.000015},
        "openai/gpt-4o": {
            "input_cost_per_token": 0.000005,
            "output_cost_per_token": 0.000015,
        },
        "azure/gpt-4o": {
            "input_cost_per_token": 0.0000028,
            "output_cost_per_token": 0.0000112,
        },
        "anthropic/claude-3-5-sonnet-20241022": {
            "input_cost_per_token": 0.000003,
            "output_cost_per_token": 0.000015,
        },
        "text-embedding-3-large": {"input_cost_per_token": 0.00000013},
        "whisper-1": {"input_cost_per_second": 0.0001},
    }


def test_provider_prefix_wins_over_bare_name(migration_module, cost_map):
    """Azure-served gpt-4o must pick up azure/ prices, not the bare entry."""
    info = migration_module._lookup(cost_map, ["gpt-4o"], "azure")
    assert info is not None
    assert info["input_cost_per_token"] == pytest.approx(0.0000028)


def test_openai_prefix_resolves_to_openai_entry(migration_module, cost_map):
    info = migration_module._lookup(cost_map, ["gpt-4o"], "openai")
    assert info is not None
    assert info["input_cost_per_token"] == pytest.approx(0.000005)


def test_falls_back_to_bare_name_when_prefixed_missing(migration_module, cost_map):
    """text-embedding-3-large only exists bare in LiteLLM — must still resolve
    for an OpenAI tenant."""
    info = migration_module._lookup(cost_map, ["text-embedding-3-large"], "openai")
    assert info is not None
    assert info["input_cost_per_token"] == pytest.approx(0.00000013)


def test_global_model_with_unambiguous_prefix_resolves(migration_module, cost_map):
    """Global model named claude-3-5-... has only one prefix in LiteLLM, so
    backfill can safely use it."""
    info = migration_module._lookup(cost_map, ["claude-3-5-sonnet-20241022"], None)
    assert info is not None
    assert info["input_cost_per_token"] == pytest.approx(0.000003)


def test_global_model_with_ambiguous_prefix_is_skipped(migration_module, cost_map):
    """gpt-4o lives under both openai/ and azure/ in LiteLLM. For a global
    model without a configured provider, we must not gamble — return None."""
    cost_map_no_bare = {k: v for k, v in cost_map.items() if k != "gpt-4o"}
    info = migration_module._lookup(cost_map_no_bare, ["gpt-4o"], None)
    assert info is None


def test_global_model_exact_match_wins_over_ambiguous_prefix(
    migration_module, cost_map
):
    """When the bare name exists in LiteLLM, use it without consulting prefixes."""
    info = migration_module._lookup(cost_map, ["gpt-4o"], None)
    assert info is not None
    assert info["input_cost_per_token"] == pytest.approx(0.000005)


def test_litellm_model_name_takes_precedence(migration_module, cost_map):
    """An operator override (litellm_model_name) is the first candidate tried."""
    info = migration_module._lookup(cost_map, ["azure/gpt-4o", "gpt-4o"], None)
    assert info is not None
    assert info["input_cost_per_token"] == pytest.approx(0.0000028)


def test_returns_none_when_nothing_matches(migration_module, cost_map):
    assert migration_module._lookup(cost_map, ["nonexistent-model"], "openai") is None
    assert migration_module._lookup(cost_map, ["nonexistent-model"], None) is None


def test_empty_names_returns_none(migration_module, cost_map):
    assert migration_module._lookup(cost_map, [None, ""], "openai") is None


def test_is_ambiguous_flags_multi_provider_names(migration_module, cost_map):
    """Sanity-check the helper used for the skipped-count summary."""
    cost_map_no_bare = {k: v for k, v in cost_map.items() if k != "gpt-4o"}
    assert migration_module._is_ambiguous(cost_map_no_bare, "gpt-4o") is True
    assert migration_module._is_ambiguous(cost_map, "gpt-4o") is False  # bare exists
    assert (
        migration_module._is_ambiguous(cost_map, "claude-3-5-sonnet-20241022") is False
    )
    assert migration_module._is_ambiguous(cost_map, None) is False
