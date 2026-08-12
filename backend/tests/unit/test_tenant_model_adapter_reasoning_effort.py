from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)


@pytest.mark.parametrize("effort", ["low", "high", "xhigh"])
def test_reasoning_effort_reaches_litellm_when_the_model_supports_it(
    effort: str,
) -> None:
    adapter = object.__new__(TenantModelAdapter)
    adapter.credential_resolver = Mock()
    adapter.litellm_model = "openai/reasoning-model"
    adapter.provider_type = "openai"
    adapter.model = SimpleNamespace(max_output_tokens=4096)

    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter."
            "build_litellm_provider_kwargs",
            return_value={},
        ),
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter."
            "_get_supported_openai_params",
            return_value=["reasoning_effort"],
        ),
    ):
        kwargs = adapter._prepare_kwargs(
            model_kwargs=ModelKwargs(reasoning_effort=effort)
        )

    assert kwargs["reasoning_effort"] == effort


@pytest.mark.parametrize(
    "model_info",
    [
        {},
        {"supports_none_reasoning_effort": False},
        RuntimeError("model metadata unavailable"),
    ],
)
def test_legacy_none_effort_is_omitted_without_explicit_route_support(
    model_info: dict[str, object] | Exception,
) -> None:
    adapter = object.__new__(TenantModelAdapter)
    adapter.credential_resolver = Mock()
    adapter.litellm_model = "openai/reasoning-model"
    adapter.provider_type = "openai"
    adapter.model = SimpleNamespace(max_output_tokens=4096)

    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter."
            "build_litellm_provider_kwargs",
            return_value={},
        ),
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter."
            "_get_supported_openai_params",
            return_value=["reasoning_effort"],
        ),
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter."
            "litellm_transport.get_model_info",
            side_effect=model_info if isinstance(model_info, Exception) else None,
            return_value=model_info if isinstance(model_info, dict) else None,
        ),
    ):
        kwargs = adapter._prepare_kwargs(
            model_kwargs=ModelKwargs(reasoning_effort="none")
        )

    assert "reasoning_effort" not in kwargs


def test_none_effort_reaches_litellm_with_explicit_route_support() -> None:
    adapter = object.__new__(TenantModelAdapter)
    adapter.credential_resolver = Mock()
    adapter.litellm_model = "openai/reasoning-model"
    adapter.provider_type = "openai"
    adapter.model = SimpleNamespace(max_output_tokens=4096)

    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter."
            "build_litellm_provider_kwargs",
            return_value={},
        ),
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter."
            "_get_supported_openai_params",
            return_value=["reasoning_effort"],
        ),
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter."
            "litellm_transport.get_model_info",
            return_value={"supports_none_reasoning_effort": True},
        ),
    ):
        kwargs = adapter._prepare_kwargs(
            model_kwargs=ModelKwargs(reasoning_effort="none")
        )

    assert kwargs["reasoning_effort"] == "none"
