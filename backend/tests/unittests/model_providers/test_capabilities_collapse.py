"""End-to-end test of capabilities endpoint logic with a synthetic litellm.model_cost."""

from typing import Any
from unittest.mock import patch

import pytest

from intric.model_providers.presentation import model_provider_router


@pytest.mark.asyncio
async def test_capabilities_collapses_dated_snapshots_into_alias() -> None:
    fake_cost: dict[str, dict[str, Any]] = {
        # Anthropic: alias + dated snapshot. Dated should be collapsed away.
        "claude-opus-4-7": {
            "litellm_provider": "anthropic",
            "mode": "chat",
            "max_input_tokens": 200000,
            "max_output_tokens": 8000,
        },
        "claude-opus-4-7-20260416": {
            "litellm_provider": "anthropic",
            "mode": "chat",
            "max_input_tokens": 200000,
            "max_output_tokens": 8000,
        },
        # Anthropic: dated-only (no alias) — must be retained.
        "claude-3-haiku-20240307": {
            "litellm_provider": "anthropic",
            "mode": "chat",
            "max_input_tokens": 100000,
            "max_output_tokens": 4000,
        },
        # OpenAI: alias + dated snapshot.
        "gpt-4o": {
            "litellm_provider": "openai",
            "mode": "chat",
            "max_input_tokens": 128000,
            "max_output_tokens": 16000,
        },
        "gpt-4o-2024-08-06": {
            "litellm_provider": "openai",
            "mode": "chat",
            "max_input_tokens": 128000,
            "max_output_tokens": 16000,
        },
        # Latest alias (filtered by existing rule).
        "gpt-4o-latest": {
            "litellm_provider": "openai",
            "mode": "chat",
            "max_input_tokens": 128000,
            "max_output_tokens": 16000,
        },
        # Embedded numeric that is NOT a date (gpt-4-0314) — keep as-is.
        "gpt-4-0314": {
            "litellm_provider": "openai",
            "mode": "chat",
            "max_input_tokens": 8000,
            "max_output_tokens": 4000,
        },
    }

    with patch.object(model_provider_router, "re", model_provider_router.re):
        with patch("litellm.model_cost", fake_cost):
            result = await model_provider_router.get_provider_capabilities(_user=None)  # type: ignore[arg-type]

    providers = result["providers"]
    assert isinstance(providers, dict)

    anthropic_completion_names = {
        m["name"] for m in providers["anthropic"]["models"]["completion"]
    }
    # Alias kept, dated-with-alias collapsed, dated-only kept
    assert anthropic_completion_names == {
        "claude-opus-4-7",
        "claude-3-haiku-20240307",
    }

    openai_completion_names = {
        m["name"] for m in providers["openai"]["models"]["completion"]
    }
    # gpt-4o (alias) kept, gpt-4o-2024-08-06 collapsed away,
    # gpt-4o-latest filtered by -latest rule, gpt-4-0314 kept (not a date suffix)
    assert openai_completion_names == {"gpt-4o", "gpt-4-0314"}
