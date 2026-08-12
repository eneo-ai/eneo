from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)


@pytest.mark.parametrize("effort", ["high", "none"])
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
