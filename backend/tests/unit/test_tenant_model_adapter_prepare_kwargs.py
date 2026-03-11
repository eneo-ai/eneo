from types import SimpleNamespace
from unittest.mock import patch


from intric.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)


def _make_adapter(provider_type: str = "openai", token_limit: int = 64000) -> TenantModelAdapter:
    """Create a minimal TenantModelAdapter for _prepare_kwargs testing."""
    adapter = object.__new__(TenantModelAdapter)
    adapter.litellm_model = f"{provider_type}/test-model"
    adapter.model = SimpleNamespace(name="test-model", token_limit=token_limit)
    adapter.provider_type = provider_type
    adapter.credential_resolver = SimpleNamespace(
        get_api_key=lambda: "test-key",
        get_credential_field=lambda field: None,
    )
    return adapter


class TestPrepareKwargsMaxTokens:
    """Tests for max_tokens injection logic in _prepare_kwargs."""

    def test_injects_default_max_tokens_when_no_reasoning(self):
        """Normal case: no reasoning_effort → inject default max_tokens."""
        adapter = _make_adapter("openai", token_limit=64000)
        result = adapter._prepare_kwargs(model_kwargs={"temperature": 0.7})
        assert result["max_tokens"] == 4096

    def test_injects_default_max_tokens_for_non_anthropic_with_reasoning(self):
        """Non-Anthropic provider with reasoning_effort → still inject max_tokens."""
        adapter = _make_adapter("openai", token_limit=64000)
        with patch("intric.completion_models.infrastructure.adapters.tenant_model_adapter.litellm") as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": "high"})
        assert result["max_tokens"] == 4096

    def test_skips_max_tokens_for_anthropic_with_reasoning(self):
        """Anthropic + reasoning_effort → defer to LiteLLM (no max_tokens injected)."""
        adapter = _make_adapter("anthropic", token_limit=64000)
        with patch("intric.completion_models.infrastructure.adapters.tenant_model_adapter.litellm") as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": "high"})
        assert "max_tokens" not in result

    def test_skips_max_tokens_for_anthropic_with_reasoning_low(self):
        """Anthropic + reasoning_effort=low → also defer to LiteLLM."""
        adapter = _make_adapter("anthropic", token_limit=64000)
        with patch("intric.completion_models.infrastructure.adapters.tenant_model_adapter.litellm") as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": "low"})
        assert "max_tokens" not in result

    def test_preserves_explicit_max_tokens_for_anthropic_with_reasoning(self):
        """Anthropic + reasoning + explicit max_tokens → pass through unchanged."""
        adapter = _make_adapter("anthropic", token_limit=64000)
        with patch("intric.completion_models.infrastructure.adapters.tenant_model_adapter.litellm") as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(
                model_kwargs={"reasoning_effort": "high", "max_tokens": 16000}
            )
        assert result["max_tokens"] == 16000

    def test_preserves_explicit_max_completion_tokens(self):
        """Anthropic + reasoning + explicit max_completion_tokens → pass through."""
        adapter = _make_adapter("anthropic", token_limit=64000)
        with patch("intric.completion_models.infrastructure.adapters.tenant_model_adapter.litellm") as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(
                model_kwargs={"reasoning_effort": "high", "max_completion_tokens": 8000}
            )
        assert result["max_completion_tokens"] == 8000
        assert "max_tokens" not in result

    def test_injects_max_tokens_when_anthropic_reasoning_unsupported(self):
        """Anthropic model that doesn't support reasoning → inject default max_tokens."""
        adapter = _make_adapter("anthropic", token_limit=64000)
        with patch("intric.completion_models.infrastructure.adapters.tenant_model_adapter.litellm") as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = []
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": "high"})
        # reasoning_effort removed by guard → normal max_tokens injection
        assert result["max_tokens"] == 4096
        assert "reasoning_effort" not in result

    def test_injects_max_tokens_when_reasoning_effort_empty(self):
        """Anthropic + empty reasoning_effort → guard removes it, inject max_tokens."""
        adapter = _make_adapter("anthropic", token_limit=64000)
        with patch("intric.completion_models.infrastructure.adapters.tenant_model_adapter.litellm") as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": ""})
        assert result["max_tokens"] == 4096
        assert "reasoning_effort" not in result

    def test_max_tokens_respects_token_limit(self):
        """Default max_tokens uses min(token_limit // 4, 4096)."""
        adapter = _make_adapter("openai", token_limit=8000)
        result = adapter._prepare_kwargs(model_kwargs={"temperature": 0.5})
        assert result["max_tokens"] == 2000  # 8000 // 4 = 2000 < 4096

    def test_no_model_kwargs_injects_nothing(self):
        """No model_kwargs → no max_tokens injection (no model_kwargs block runs)."""
        adapter = _make_adapter("openai")
        result = adapter._prepare_kwargs(model_kwargs=None)
        assert "max_tokens" not in result
