from types import SimpleNamespace
from unittest.mock import patch

import pytest

from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)


def _make_adapter(
    provider_type: str = "openai",
    token_limit: int = 64000,
    max_output_tokens: int = 12000,
) -> TenantModelAdapter:
    """Create a minimal TenantModelAdapter for _prepare_kwargs testing."""
    adapter = object.__new__(TenantModelAdapter)
    adapter.litellm_model = f"{provider_type}/test-model"
    adapter.model = SimpleNamespace(
        name="test-model",
        token_limit=token_limit,
        max_input_tokens=token_limit,
        max_output_tokens=max_output_tokens,
    )
    adapter.provider_type = provider_type
    adapter.credential_resolver = SimpleNamespace(
        provider_type=provider_type,
        get_api_key=lambda *, required=False: "test-key",
        get_credential_field=lambda *, field, required=False: None,
    )
    return adapter


class TestPrepareKwargsMaxTokens:
    """Tests for max_tokens injection logic in _prepare_kwargs."""

    def test_injects_default_max_tokens_when_no_reasoning(self):
        """Normal case: no reasoning_effort → inject default max_tokens."""
        adapter = _make_adapter("openai", token_limit=64000)
        result = adapter._prepare_kwargs(model_kwargs={"temperature": 0.7})
        assert result["max_tokens"] == 12000

    def test_injects_default_max_tokens_for_non_anthropic_with_reasoning(self):
        """Non-Anthropic provider with reasoning_effort → still inject max_tokens."""
        adapter = _make_adapter("openai", token_limit=64000)
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": "high"})
        assert result["max_tokens"] == 12000

    def test_skips_max_tokens_for_anthropic_with_reasoning(self):
        """Anthropic + reasoning_effort → defer to LiteLLM (no max_tokens injected)."""
        adapter = _make_adapter("anthropic", token_limit=64000)
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": "high"})
        assert "max_tokens" not in result

    def test_skips_max_tokens_for_anthropic_with_reasoning_low(self):
        """Anthropic + reasoning_effort=low → also defer to LiteLLM."""
        adapter = _make_adapter("anthropic", token_limit=64000)
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": "low"})
        assert "max_tokens" not in result

    def test_preserves_explicit_max_tokens_for_anthropic_with_reasoning(self):
        """Anthropic + reasoning + explicit max_tokens → pass through unchanged."""
        adapter = _make_adapter("anthropic", token_limit=64000)
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(
                model_kwargs={"reasoning_effort": "high", "max_tokens": 16000}
            )
        assert result["max_tokens"] == 16000

    def test_preserves_explicit_max_completion_tokens(self):
        """Anthropic + reasoning + explicit max_completion_tokens → pass through."""
        adapter = _make_adapter("anthropic", token_limit=64000)
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(
                model_kwargs={"reasoning_effort": "high", "max_completion_tokens": 8000}
            )
        assert result["max_completion_tokens"] == 8000
        assert "max_tokens" not in result

    def test_injects_max_tokens_when_anthropic_reasoning_unsupported(self):
        """Anthropic model that doesn't support reasoning → inject default max_tokens."""
        adapter = _make_adapter("anthropic", token_limit=64000)
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = []
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": "high"})
        # reasoning_effort removed by guard → normal max_tokens injection
        assert result["max_tokens"] == 12000
        assert "reasoning_effort" not in result

    def test_injects_max_tokens_when_reasoning_effort_empty(self):
        """Anthropic + empty reasoning_effort → guard removes it, inject max_tokens."""
        adapter = _make_adapter("anthropic", token_limit=64000)
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": ""})
        assert result["max_tokens"] == 12000
        assert "reasoning_effort" not in result

    def test_max_tokens_uses_stored_max_output_tokens(self):
        """Default max_tokens uses the model's explicit max_output_tokens."""
        adapter = _make_adapter("openai", token_limit=8000, max_output_tokens=6000)
        result = adapter._prepare_kwargs(model_kwargs={"temperature": 0.5})
        assert result["max_tokens"] == 6000

    def test_get_token_limit_uses_input_minus_output_budget(self):
        """The configured input budget is already independent of output."""
        adapter = _make_adapter("openai", token_limit=128000, max_output_tokens=32000)
        assert adapter.get_token_limit_of_model() == 128000

    def test_no_model_kwargs_injects_nothing(self):
        """No model_kwargs → no max_tokens injection (no model_kwargs block runs)."""
        adapter = _make_adapter("openai")
        result = adapter._prepare_kwargs(model_kwargs=None)
        assert "max_tokens" not in result


class TestPrepareKwargsReasoningEffortTranslation:
    """Translate 'none'/empty reasoning_effort instead of dropping silently.

    Dropping reasoning_effort lets reasoning models fall back to their
    default effort (medium/high on the gpt-5 family), which contributes
    to multi-minute single-call latency. When the caller signals
    minimum reasoning, translate to the lowest supported value rather
    than handing the model no signal.
    """

    def test_openai_translates_none_reasoning_effort_to_low(self):
        adapter = _make_adapter("openai")
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": "none"})
        assert result["reasoning_effort"] == "low"

    def test_openai_translates_empty_reasoning_effort_to_low(self):
        adapter = _make_adapter("openai")
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": ""})
        assert result["reasoning_effort"] == "low"

    def test_openai_translates_none_object_reasoning_effort_to_low(self):
        adapter = _make_adapter("openai")
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": None})
        assert result["reasoning_effort"] == "low"

    def test_openai_preserves_explicit_reasoning_effort(self):
        adapter = _make_adapter("openai")
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": "high"})
        assert result["reasoning_effort"] == "high"

    def test_openai_drops_when_model_does_not_support_reasoning_effort(self):
        """Unsupported by the model → drop. Translation is for the
        capability-present-but-explicit-off case only."""
        adapter = _make_adapter("openai")
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = []
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": "none"})
        assert "reasoning_effort" not in result

    def test_capability_lookup_failure_stops_before_provider_preparation(self):
        adapter = _make_adapter("openai")
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.side_effect = RuntimeError(
                "capability registry unavailable"
            )
            with pytest.raises(RuntimeError, match="capability registry unavailable"):
                adapter._prepare_kwargs(model_kwargs={"reasoning_effort": "high"})

    def test_anthropic_drops_none_reasoning_effort(self):
        """Anthropic uses LiteLLM's extended-thinking mapping; explicit
        'no thinking' is best expressed by absence, not 'low'."""
        adapter = _make_adapter("anthropic")
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": "none"})
        assert "reasoning_effort" not in result

    def test_openai_translates_pydantic_none_reasoning_effort_to_low(self):
        """Production callers pass a Pydantic ModelKwargs, not a dict.

        ModelKwargs(reasoning_effort=None) — the wire shape produced when
        the UI's 'Default' option is selected — gets stripped by
        model_dump(exclude_none=True) before the explicit-off-signal
        branch runs, so the dict-only translation never fires in
        production. Apply the same 'low' floor when the key is absent
        on an OpenAI model that supports reasoning_effort, otherwise
        the runtime silently defaults to medium/high effort and we
        regain the multi-minute first-token latency we set out to fix.
        """
        from eneo.ai_models.completion_models.completion_model import ModelKwargs

        adapter = _make_adapter("openai")
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(
                model_kwargs=ModelKwargs(reasoning_effort=None)
            )
        assert result["reasoning_effort"] == "low"

    def test_anthropic_pydantic_none_reasoning_effort_does_not_inject(self):
        """The Pydantic-None floor must not inject reasoning_effort on
        Anthropic — there, absence is the correct 'no thinking' signal
        and a synthesized value would force extended-thinking on every
        call."""
        from eneo.ai_models.completion_models.completion_model import ModelKwargs

        adapter = _make_adapter("anthropic")
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(
                model_kwargs=ModelKwargs(reasoning_effort=None)
            )
        assert "reasoning_effort" not in result

    def test_openai_non_reasoning_model_pydantic_none_does_not_inject(self):
        """Models that don't support reasoning_effort must not have it
        injected by the Pydantic-None floor."""
        from eneo.ai_models.completion_models.completion_model import ModelKwargs

        adapter = _make_adapter("openai")
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = []
            result = adapter._prepare_kwargs(
                model_kwargs=ModelKwargs(reasoning_effort=None)
            )
        assert "reasoning_effort" not in result
