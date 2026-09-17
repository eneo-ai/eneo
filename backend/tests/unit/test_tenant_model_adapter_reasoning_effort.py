import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import httpx
import pytest
from litellm.constants import (
    DEFAULT_REASONING_EFFORT_HIGH_THINKING_BUDGET as THINKING_BUDGET,
)

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.completion_models.domain.model_kwargs_capabilities import (
    reasoning_effort_options_from_model_info,
    snapshot_supported_model_kwargs,
)
from eneo.completion_models.infrastructure.adapters.base_adapter import ProviderInput
from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)
from eneo.governance_policy.domain.policy_resolver import (
    EffectiveConfig,
    select_effective_reasoning_effort,
)
from eneo.main.exceptions import ProviderRejectedRequestException
from eneo.tokens.token_utils import measure_provider_input_reserve


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "model", "cap", "rejected"),
    [
        ("anthropic", "claude-3-7-sonnet-20250219", 512, True),
        ("anthropic", "claude-3-7-sonnet-20250219", THINKING_BUDGET, True),
        ("anthropic", "claude-3-7-sonnet-20250219", THINKING_BUDGET + 1, False),
        ("anthropic", "claude-sonnet-4-6", 512, False),
        ("openai", "gpt-5", 512, False),
        ("hosted_vllm", "reasoning-model", 512, False),
    ],
)
@pytest.mark.parametrize("cap_parameter", [None, "max_tokens", "max_completion_tokens"])
@pytest.mark.parametrize("constraint", ["output", "input", "caller"])
async def test_reasoning_dispatch_preserves_cap_and_effort_after_sdk_normalization(
    provider, model, cap, rejected, cap_parameter, constraint, monkeypatch
):
    if constraint == "caller" and cap_parameter is None:
        pytest.skip("A caller ceiling requires a caller cap")
    adapter = object.__new__(TenantModelAdapter)
    adapter.litellm_model = f"{provider}/{model}"
    adapter.provider_type = provider
    messages = [{"role": "user", "content": "hello"}]
    reserve = measure_provider_input_reserve(messages, [], adapter.litellm_model).tokens
    adapter.model = SimpleNamespace(
        token_limit=reserve + (cap if constraint == "input" else 64000),
        max_output_tokens=cap if constraint == "output" else 64000,
    )
    adapter.credential_resolver = SimpleNamespace(
        provider_type=provider,
        get_api_key=lambda **kwargs: "test-key",
        get_credential_field=lambda **kwargs: None,
    )
    adapter.prepare_provider_input = Mock(
        return_value=ProviderInput(messages=messages, tools=[], built_in_tools=[])
    )
    observer = SimpleNamespace(
        started=AsyncMock(return_value=uuid4()),
        rejected=AsyncMock(),
        completed=AsyncMock(),
        outcome_unknown=AsyncMock(),
    )
    requests = []

    async def capture_request(client, request, **kwargs):
        requests.append(json.loads(await request.aread()))
        if rejected:
            return httpx.Response(
                400,
                request=request,
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "max_tokens must be greater than thinking.budget_tokens",
                    },
                },
            )
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "response-1",
                "type": "message",
                "object": "chat.completion",
                "created": 1,
                "role": "assistant",
                "model": model,
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", capture_request)
    model_kwargs = {"reasoning_effort": "high"}
    if cap_parameter is not None:
        model_kwargs[cap_parameter] = cap if constraint == "caller" else 64000

    async def dispatch():
        return await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs=model_kwargs,
            provider_call_observer=observer,
            api_base="https://provider.example/v1",
            num_retries=0,
            max_retries=0,
        )

    if rejected:
        with pytest.raises(ProviderRejectedRequestException) as error:
            await dispatch()
        assert error.value.code == "provider_rejected_request"
        assert error.value.details["retryable"] is False
        observer.rejected.assert_awaited_once_with(
            observer.started.return_value, "provider_rejected"
        )
        observer.completed.assert_not_awaited()
    else:
        assert (await dispatch()).text == "ok"
        observer.completed.assert_awaited_once()
        observer.rejected.assert_not_awaited()
    observer.started.assert_awaited_once()
    observer.outcome_unknown.assert_not_awaited()
    assert len(requests) == 1
    outbound = requests[0]
    assert outbound["model"] == model
    assert outbound.get("max_completion_tokens", outbound.get("max_tokens")) == cap
    if provider == "anthropic":
        if model == "claude-sonnet-4-6":
            assert outbound["thinking"]["type"] == "adaptive"
            assert outbound["output_config"]["effort"] == "high"
        else:
            assert outbound["thinking"] == {
                "type": "enabled",
                "budget_tokens": THINKING_BUDGET,
            }
    else:
        assert outbound["reasoning_effort"] == "high"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "model"), [("openai", "gpt-4o-mini"), ("mistral", "plain-model")]
)
@pytest.mark.parametrize("effort", [None, "high", "none"])
@pytest.mark.parametrize("method", ["get_response", "prepare_streaming"])
async def test_unsupported_reasoning_is_refused_before_sdk_dispatch(
    provider, model, effort, method, monkeypatch
):
    adapter = object.__new__(TenantModelAdapter)
    adapter.litellm_model = f"{provider}/{model}"
    adapter.provider_type = provider
    adapter.model = SimpleNamespace(token_limit=5000, max_output_tokens=64)
    adapter.credential_resolver = SimpleNamespace(
        provider_type=provider,
        get_api_key=lambda **kwargs: "test-key",
        get_credential_field=lambda **kwargs: None,
    )
    adapter.prepare_provider_input = Mock(
        return_value=ProviderInput(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
            built_in_tools=[],
        )
    )
    observer = SimpleNamespace(
        started=AsyncMock(return_value=uuid4()),
        rejected=AsyncMock(),
        completed=AsyncMock(),
        outcome_unknown=AsyncMock(),
    )
    requests = []

    async def capture_request(client, request, **kwargs):
        requests.append(json.loads(await request.aread()))
        completion = {
            "id": "response-1",
            "object": "chat.completion",
            "created": 1,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
        }
        return httpx.Response(200, request=request, json=completion)

    monkeypatch.setattr(httpx.AsyncClient, "send", capture_request)
    call_kwargs = (
        {"provider_call_observer": observer} if method == "get_response" else {}
    )

    async def dispatch():
        return await getattr(adapter, method)(
            context=SimpleNamespace(),
            model_kwargs={"reasoning_effort": effort} if effort is not None else {},
            api_base="https://provider.example/v1",
            num_retries=0,
            max_retries=0,
            **call_kwargs,
        )

    if effort is not None:
        with pytest.raises(ProviderRejectedRequestException) as error:
            await dispatch()
        assert error.value.code == "provider_rejected_request"
        assert error.value.details["retryable"] is False
        assert requests == []
        observer.started.assert_not_awaited()
        observer.completed.assert_not_awaited()
    else:
        await dispatch()
        assert len(requests) == 1
        assert "reasoning_effort" not in requests[0]
        assert requests[0]["max_tokens"] == 64


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
            "eneo.completion_models.infrastructure.tenant_model_capabilities."
            "get_supported_openai_params",
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
def test_explicit_none_effort_is_preserved_without_value_metadata(
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
            "eneo.completion_models.infrastructure.tenant_model_capabilities."
            "get_supported_openai_params",
            return_value=["reasoning_effort"],
        ),
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities."
            "litellm.get_model_info",
            side_effect=model_info if isinstance(model_info, Exception) else None,
            return_value=model_info if isinstance(model_info, dict) else None,
        ),
    ):
        kwargs = adapter._prepare_kwargs(
            model_kwargs=ModelKwargs(reasoning_effort="none")
        )

    assert kwargs["reasoning_effort"] == "none"


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
            "eneo.completion_models.infrastructure.tenant_model_capabilities."
            "get_supported_openai_params",
            return_value=["reasoning_effort"],
        ),
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities."
            "litellm.get_model_info",
            return_value=model_info,
        ),
    ):
        kwargs = adapter._prepare_kwargs(
            model_kwargs=ModelKwargs(reasoning_effort=selected_effort)
        )

    assert kwargs["reasoning_effort"] == "none"
