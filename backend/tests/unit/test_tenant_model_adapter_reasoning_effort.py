import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import httpx
import litellm
import pytest
from litellm.exceptions import BadRequestError
from litellm.types.utils import LlmProviders
from litellm.utils import ProviderConfigManager
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
from eneo.completion_models.infrastructure import tenant_model_capabilities
from eneo.completion_models.infrastructure.adapters.base_adapter import ProviderInput
from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)
from eneo.governance_policy.domain.policy_resolver import (
    EffectiveConfig,
    select_effective_reasoning_effort,
)
from eneo.main.exceptions import ProviderRejectedRequestException
from eneo.model_providers.infrastructure import litellm_transport
from eneo.tokens.token_utils import measure_provider_input_reserve

TRANSPORT = "openai"
MODEL = "model-a"


@pytest.fixture
def reasoning_route(monkeypatch):
    params = [
        "max_tokens",
        "max_completion_tokens",
        "stream",
        "max_retries",
        "reasoning_effort",
    ]
    options = ["high", "none"]
    config = ProviderConfigManager.get_provider_chat_config(
        model=MODEL, provider=LlmProviders(TRANSPORT)
    )
    assert config is not None
    monkeypatch.setattr(
        type(config), "get_supported_openai_params", lambda *args, **kwargs: params
    )
    monkeypatch.setattr(
        litellm, "get_supported_openai_params", lambda *args, **kwargs: params
    )
    monkeypatch.setattr(
        tenant_model_capabilities,
        "resolve_reasoning_effort_options",
        lambda **kwargs: options,
    )
    adapter = object.__new__(TenantModelAdapter)
    adapter.litellm_model = f"{TRANSPORT}/{MODEL}"
    adapter.provider_type = TRANSPORT
    adapter.model = SimpleNamespace(token_limit=5000, max_output_tokens=64)
    adapter.credential_resolver = SimpleNamespace(
        provider_type=TRANSPORT,
        get_api_key=lambda **kwargs: "test-key",
        get_credential_field=lambda **kwargs: None,
    )
    messages = [{"role": "user", "content": "hello"}]
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
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "response-1",
                "object": "chat.completion",
                "created": 1,
                "model": MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
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

    monkeypatch.setattr(httpx.AsyncClient, "send", capture_request)

    async def dispatch(model_kwargs, method="get_response"):
        return await getattr(adapter, method)(
            context=SimpleNamespace(),
            model_kwargs=model_kwargs,
            # The cap arithmetic here uses toy limits below the default
            # useful-output reserve; that gate is covered elsewhere.
            useful_output_reserve_tokens=1,
            api_base="https://provider.example/v1",
            num_retries=0,
            max_retries=0,
            **(
                {"provider_call_observer": observer} if method == "get_response" else {}
            ),
        )

    return SimpleNamespace(
        adapter=adapter,
        observer=observer,
        requests=requests,
        dispatch=dispatch,
        messages=messages,
        params=params,
        options=options,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("input_room", "output_limit", "caller_kwargs"),
    [
        (1000, 64, {}),
        (64, 1000, {}),
        (1000, 64, {"max_tokens": 1000}),
        (64, 1000, {"max_completion_tokens": 1000}),
        (1000, 1000, {"max_tokens": 32}),
        (1000, 1000, {"max_completion_tokens": 32}),
    ],
)
async def test_reasoning_dispatch_preserves_bounded_cap_on_wire(
    input_room, output_limit, caller_kwargs, reasoning_route
):
    route = reasoning_route
    reserve = measure_provider_input_reserve(
        route.messages, [], route.adapter.litellm_model
    ).tokens
    route.adapter.model.token_limit = reserve + input_room
    route.adapter.model.max_output_tokens = output_limit
    assert (
        await route.dispatch({"reasoning_effort": "high", **caller_kwargs})
    ).text == "ok"
    assert len(route.requests) == 1
    outbound = route.requests[0]
    assert outbound["model"] == MODEL
    assert outbound["max_tokens"] == min(
        output_limit, input_room, *caller_kwargs.values()
    )
    assert outbound["reasoning_effort"] == "high"
    route.observer.started.assert_awaited_once()
    route.observer.completed.assert_awaited_once()
    route.observer.rejected.assert_not_awaited()
    route.observer.outcome_unknown.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("effort", "supported", "none_supported"),
    [
        (None, False, False),
        (None, True, True),
        ("high", False, False),
        ("high", True, False),
        ("none", False, False),
        ("none", True, False),
        ("none", True, True),
    ],
)
@pytest.mark.parametrize("method", ["get_response", "prepare_streaming"])
async def test_reasoning_dispatch_preserves_or_refuses_explicit_choices(
    effort, supported, none_supported, method, reasoning_route
):
    route = reasoning_route
    if not supported:
        route.params.remove("reasoning_effort")
    if not none_supported:
        route.options.remove("none")
    kwargs = {"reasoning_effort": effort} if effort is not None else {}
    if effort is not None and (not supported or effort not in route.options):
        with pytest.raises(ProviderRejectedRequestException) as error:
            await route.dispatch(kwargs, method)
        assert error.value.code == "provider_rejected_request"
        assert error.value.details == {
            "reason": "reasoning_effort_unsupported",
            "retryable": False,
        }
        assert route.requests == []
        route.observer.started.assert_not_awaited()
        route.observer.completed.assert_not_awaited()
    else:
        await route.dispatch(kwargs, method)
        assert len(route.requests) == 1
        if effort is None:
            assert "reasoning_effort" not in route.requests[0]
        else:
            assert route.requests[0]["reasoning_effort"] == effort
        assert route.requests[0]["max_tokens"] == 64
        if method == "get_response":
            route.observer.started.assert_awaited_once()
            route.observer.completed.assert_awaited_once()
    route.observer.rejected.assert_not_awaited()
    route.observer.outcome_unknown.assert_not_awaited()


@pytest.mark.asyncio
async def test_sdk_validation_refusal_is_observed_as_non_retryable(
    reasoning_route, monkeypatch
):
    route = reasoning_route
    sdk = AsyncMock(
        side_effect=BadRequestError(
            message="Requested controls cannot be combined",
            model=MODEL,
            llm_provider=TRANSPORT,
        )
    )
    monkeypatch.setattr(litellm, "acompletion", sdk)
    with pytest.raises(ProviderRejectedRequestException) as error:
        await route.dispatch({"reasoning_effort": "high"})
    assert error.value.code == "provider_rejected_request"
    assert error.value.details["retryable"] is False
    sdk.assert_awaited_once()
    assert sdk.call_args.kwargs["reasoning_effort"] == "high"
    assert sdk.call_args.kwargs["max_tokens"] == 64
    assert sdk.call_args.kwargs["model"] == route.adapter.litellm_model
    assert route.requests == []
    route.observer.started.assert_awaited_once()
    route.observer.rejected.assert_awaited_once_with(
        route.observer.started.return_value, "provider_rejected"
    )
    route.observer.completed.assert_not_awaited()
    route.observer.outcome_unknown.assert_not_awaited()


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
def test_none_effort_is_refused_without_value_metadata(
    model_info: dict[str, object] | Exception,
) -> None:
    adapter = object.__new__(TenantModelAdapter)
    adapter.credential_resolver = Mock()
    adapter.litellm_model = f"{TRANSPORT}/{MODEL}"
    adapter.provider_type = TRANSPORT
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
        with pytest.raises(ProviderRejectedRequestException) as error:
            adapter._prepare_kwargs(model_kwargs=ModelKwargs(reasoning_effort="none"))

    assert error.value.details["reason"] == "reasoning_effort_unsupported"
    assert error.value.details["retryable"] is False


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
