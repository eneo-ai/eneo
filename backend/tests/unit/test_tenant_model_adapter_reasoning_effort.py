import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx
import pytest
from openai import AsyncAzureOpenAI

from eneo.ai_models.completion_models.completion_model import (
    CompletionModel,
    ModelKwargs,
)
from eneo.completion_models.domain.completion_model import (
    CompletionModel as DomainCompletionModel,
)
from eneo.completion_models.domain.model_kwargs_capabilities import (
    SupportedModelKwargs,
    reasoning_effort_options_from_model_info,
    snapshot_supported_model_kwargs,
)
from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)
from eneo.governance_policy.domain.policy_resolver import (
    EffectiveConfig,
    select_effective_reasoning_effort,
)
from eneo.model_providers.infrastructure import litellm_transport


def _completion_model(
    supported: SupportedModelKwargs,
    *,
    provider_type: str = "azure",
    reasoning: bool = True,
) -> CompletionModel:
    return CompletionModel(
        id=uuid4(),
        name="production-chat-deployment",
        max_input_tokens=8192,
        max_output_tokens=4096,
        is_deprecated=False,
        vision=False,
        reasoning=reasoning,
        provider_type=provider_type,
        litellm_model_name=f"{provider_type}/production-chat-deployment",
        model_kwargs_capabilities=supported,
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
    model_info = {
        "supports_reasoning": True,
        "supports_none_reasoning_effort": True,
    }
    supported_kwargs = snapshot_supported_model_kwargs(
        ["reasoning_effort"],
        reasoning=True,
        reasoning_effort_options=reasoning_effort_options_from_model_info(model_info),
    )
    selected_model = SimpleNamespace(
        get_supported_model_kwargs=lambda: supported_kwargs
    )
    selected_effort = select_effective_reasoning_effort(
        selected_model=selected_model,
        stored_effort="none",
        effective_config=EffectiveConfig(
            models_enforced=False,
            available_models=[],
            locked_model=None,
            policy_default_model=None,
            mcp_enforced=False,
            available_mcp_servers=[],
            prompt_enforced=False,
            enforced_prompt_text=None,
            reasoning_policy_configured=True,
            default_reasoning_effort="high",
            reasoning_effort_user_configurable=True,
        ),
    )
    assert selected_effort == "none"

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
            return_value=model_info,
        ),
    ):
        kwargs = adapter._prepare_kwargs(
            model_kwargs=ModelKwargs(reasoning_effort=selected_effort)
        )

    assert kwargs["reasoning_effort"] == "none"


@pytest.mark.parametrize("model_type", ["domain", "response"])
@pytest.mark.parametrize("as_dict", [False, True])
@pytest.mark.parametrize(
    "effort,options,reasoning,expected",
    [
        ("none", ["none", "low", "medium", "high"], True, "none"),
        ("high", ["low", "medium", "high"], True, "high"),
        (None, ["none", "low", "medium", "high"], True, None),
        ("", ["none", "low", "medium", "high"], True, None),
        ("none", ["low", "medium", "high"], True, None),
        ("none", ["none", "low", "medium", "high"], False, None),
    ],
)
def test_azure_deployment_uses_persisted_reasoning_capabilities(
    model_type: str,
    as_dict: bool,
    effort: str | None,
    options: list[str],
    reasoning: bool,
    expected: str | None,
) -> None:
    supported = snapshot_supported_model_kwargs(
        ["reasoning_effort"],
        reasoning=True,
        reasoning_effort_options=options,
    )
    model: CompletionModel | DomainCompletionModel = _completion_model(
        supported, reasoning=reasoning
    )
    if model_type == "domain":
        domain_model = object.__new__(DomainCompletionModel)
        for name in (
            "id",
            "tenant_id",
            "provider_type",
            "litellm_model_name",
            "max_output_tokens",
            "reasoning",
            "model_kwargs_capabilities",
        ):
            setattr(domain_model, name, getattr(model, name))
        model = domain_model
    adapter = object.__new__(TenantModelAdapter)
    adapter.credential_resolver = Mock()
    adapter.litellm_model = model.litellm_model_name
    adapter.provider_type = "azure"
    adapter.model = model

    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter."
            "build_litellm_provider_kwargs",
            return_value={},
        ),
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter."
            "_get_supported_openai_params",
            return_value=None,
        ) as supported_params,
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter."
            "litellm_transport.get_model_info",
            side_effect=RuntimeError("deployment metadata unavailable"),
        ) as model_info,
    ):
        kwargs = adapter._prepare_kwargs(
            model_kwargs=(
                {"reasoning_effort": effort}
                if as_dict
                else ModelKwargs(reasoning_effort=effort)
            )
        )

    if expected is None:
        assert "reasoning_effort" not in kwargs
        assert "allowed_openai_params" not in kwargs
    else:
        assert kwargs["reasoning_effort"] == expected
        assert kwargs["allowed_openai_params"] == ["reasoning_effort"]
    supported_params.assert_not_called()
    model_info.assert_not_called()


def test_anthropic_reasoning_keeps_provider_parameter_translation() -> None:
    from litellm.utils import get_optional_params

    supported = snapshot_supported_model_kwargs(["reasoning_effort"], reasoning=True)
    adapter = object.__new__(TenantModelAdapter)
    adapter.provider_type = "anthropic"
    adapter.model = _completion_model(supported, provider_type="anthropic")
    kwargs = adapter._prepare_reasoning_effort("high")
    assert "allowed_openai_params" not in kwargs
    mapped = get_optional_params(
        model="claude-sonnet-4-5",
        custom_llm_provider="anthropic",
        drop_params=True,
        **kwargs,
    )
    assert mapped["thinking"]["type"] == "enabled"
    assert "reasoning_effort" not in mapped


@pytest.mark.parametrize("effort", ["none", None])
async def test_azure_reasoning_effort_reaches_http_request(effort: str | None) -> None:
    supported = snapshot_supported_model_kwargs(
        ["reasoning_effort"],
        reasoning=True,
        reasoning_effort_options=["none", "low", "medium", "high"],
    )
    adapter = object.__new__(TenantModelAdapter)
    adapter.credential_resolver = Mock()
    adapter.litellm_model = "azure/production-chat-deployment"
    adapter.provider_type = "azure"
    adapter.model = _completion_model(supported)
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1,
                "model": "production-chat-deployment",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hello"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter."
        "build_litellm_provider_kwargs",
        return_value={},
    ):
        kwargs = adapter._prepare_kwargs(
            model_kwargs=ModelKwargs(reasoning_effort=effort)
        )

    async with AsyncAzureOpenAI(
        api_key="test-key",
        azure_endpoint="https://azure.example",
        api_version="2025-04-01-preview",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as client:
        await litellm_transport.acompletion(
            model=adapter.litellm_model,
            client=client,
            messages=[{"role": "user", "content": "Hello"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "server__lookup",
                        "description": "Look up a case",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            drop_params=True,
            **kwargs,
        )

    [request] = requests
    payload = json.loads(request.content)
    assert payload["tools"][0]["function"]["name"] == "server__lookup"
    if effort is None:
        assert "reasoning_effort" not in payload
    else:
        assert payload["reasoning_effort"] == "none"
    assert "allowed_openai_params" not in payload
