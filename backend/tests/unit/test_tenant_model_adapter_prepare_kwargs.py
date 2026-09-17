import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
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


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_response", "prepare_streaming"])
@pytest.mark.parametrize(
    ("input_limit", "output_limit", "caller_kwargs", "expected"),
    [
        (100, 20, None, 20),
        (100, 100, {}, 90),
        (100, 200, {}, 90),
        (100, 200, {"max_tokens": 7}, 7),
        (100, 200, {"max_completion_tokens": 8}, 8),
        (100, 200, {"max_tokens": 7, "max_completion_tokens": 8}, 7),
        (11, 100, {}, 1),
    ],
)
async def test_dispatch_bounds_the_outgoing_cap(
    method, input_limit, output_limit, caller_kwargs, expected
):
    from eneo.completion_models.infrastructure.adapters.base_adapter import (
        ProviderInput,
    )

    adapter = _make_adapter(token_limit=input_limit, max_output_tokens=output_limit)
    adapter.prepare_provider_input = Mock(
        return_value=ProviderInput(
            messages=[{"role": "user", "content": "hi"}], tools=[], built_in_tools=[]
        )
    )
    observer = SimpleNamespace(started=AsyncMock(), completed=AsyncMock())
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="ok", tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=None,
    )
    transport = AsyncMock(return_value=response)
    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            transport,
        ),
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter.measure_provider_input_reserve",
            return_value=SimpleNamespace(tokens=10),
            create=True,
        ),
    ):
        await getattr(adapter, method)(
            context=SimpleNamespace(),
            model_kwargs=caller_kwargs,
            **(
                {"provider_call_observer": observer} if method == "get_response" else {}
            ),
        )
    sent = transport.await_args.kwargs
    assert sent.get("max_completion_tokens", sent.get("max_tokens")) == expected
    assert not ("max_tokens" in sent and "max_completion_tokens" in sent)
    if method == "get_response":
        observer.started.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_response", "prepare_streaming"])
@pytest.mark.parametrize(
    ("input_limit", "output_limit"),
    [(None, 20), (100, None), (10, 20), (9, 20), (1, 20)],
)
async def test_dispatch_refuses_before_transport_and_observation(
    method, input_limit, output_limit
):
    from eneo.completion_models.domain.model_capacity import UnknownModelCapacityError
    from eneo.completion_models.infrastructure.adapters.base_adapter import (
        ProviderInput,
    )
    from eneo.completion_models.infrastructure.context_builder import (
        ContextWindowExceededError,
    )

    adapter = _make_adapter(token_limit=input_limit, max_output_tokens=output_limit)
    adapter.prepare_provider_input = Mock(
        return_value=ProviderInput(messages=[], tools=[], built_in_tools=[])
    )
    observer = SimpleNamespace(started=AsyncMock())
    transport = AsyncMock()
    error = (
        UnknownModelCapacityError
        if None in (input_limit, output_limit)
        else ContextWindowExceededError
    )
    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            transport,
        ),
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter.measure_provider_input_reserve",
            return_value=SimpleNamespace(tokens=10),
            create=True,
        ),
        pytest.raises(error),
    ):
        await getattr(adapter, method)(
            context=SimpleNamespace(),
            model_kwargs={"max_tokens": 1},
            **(
                {"provider_call_observer": observer} if method == "get_response" else {}
            ),
        )
    transport.assert_not_awaited()
    observer.started.assert_not_awaited()


def test_input_packing_leaves_room_for_a_positive_answer():
    assert _make_adapter(token_limit=100).get_token_limit_of_model() == 99


class TestPrepareKwargsReasoningEffortTranslation:
    """Translate 'none'/empty reasoning_effort instead of dropping silently.

    Dropping reasoning_effort lets reasoning models fall back to their
    default effort (medium/high on the gpt-5 family), which contributes
    to multi-minute single-call latency. When the caller signals
    minimum reasoning, translate to the lowest supported value rather
    than handing the model no signal.
    """

    def test_openai_preserves_explicit_none_reasoning_effort(self):
        adapter = _make_adapter("openai")
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": "none"})
        assert result["reasoning_effort"] == "none"

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

    def test_explicit_effort_without_capability_support_is_refused(self):
        from eneo.main.exceptions import ProviderRejectedRequestException

        adapter = _make_adapter("openai")
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = []
            with pytest.raises(ProviderRejectedRequestException):
                adapter._prepare_kwargs(model_kwargs={"reasoning_effort": "none"})

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

    def test_anthropic_preserves_explicit_none_reasoning_effort(self):
        adapter = _make_adapter("anthropic")
        with patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm"
        ) as mock_litellm:
            mock_litellm.get_supported_openai_params.return_value = ["reasoning_effort"]
            result = adapter._prepare_kwargs(model_kwargs={"reasoning_effort": "none"})
        assert result["reasoning_effort"] == "none"

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


@pytest.mark.asyncio
async def test_capability_retry_and_admin_changes_remeasure_each_dispatch():
    from litellm.exceptions import BadRequestError

    from eneo.completion_models.infrastructure.adapters.base_adapter import (
        ProviderInput,
    )
    from eneo.main.exceptions import ProviderCapabilityRejectedException

    adapter = _make_adapter(token_limit=1000, max_output_tokens=1000)
    adapter.prepare_provider_input = Mock(
        return_value=ProviderInput(messages=[], tools=[], built_in_tools=[])
    )
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="ok", tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=None,
    )
    rejected = BadRequestError(
        "unsupported",
        model="test-model",
        llm_provider="openai",
        body={"error": {"code": "unsupported_parameter", "param": "response_format"}},
    )
    transport = AsyncMock(side_effect=[rejected, response, response, response])

    def reserve(messages, tools, model, *, response_format=None):
        return SimpleNamespace(tokens=100 if response_format else 10)

    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            transport,
        ),
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter.measure_provider_input_reserve",
            side_effect=reserve,
        ),
    ):
        with pytest.raises(ProviderCapabilityRejectedException):
            await adapter.get_response(
                context=SimpleNamespace(),
                model_kwargs={"response_format": {"type": "json_object"}},
            )
        await adapter.get_response(context=SimpleNamespace(), model_kwargs={})
        adapter.model.max_output_tokens = 400
        await adapter.get_response(context=SimpleNamespace(), model_kwargs={})
        adapter.model.max_output_tokens = 1000
        await adapter.get_response(context=SimpleNamespace(), model_kwargs={})
    assert [call.kwargs["max_tokens"] for call in transport.await_args_list] == [
        900,
        990,
        400,
        990,
    ]


@pytest.mark.asyncio
async def test_route_without_cap_support_refuses_before_observation():
    from eneo.completion_models.infrastructure.adapters.base_adapter import (
        ProviderInput,
    )
    from eneo.main.exceptions import ProviderRejectedRequestException

    adapter = _make_adapter()
    adapter.prepare_provider_input = Mock(
        return_value=ProviderInput(messages=[], tools=[], built_in_tools=[])
    )
    observer = SimpleNamespace(started=AsyncMock())
    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._get_supported_openai_params",
            return_value=[],
        ),
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            AsyncMock(),
        ) as transport,
        pytest.raises(ProviderRejectedRequestException) as raised,
    ):
        await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs=None,
            provider_call_observer=observer,
        )
    assert raised.value.details == {
        "reason": "output_cap_unsupported",
        "retryable": False,
    }
    transport.assert_not_awaited()
    observer.started.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("references,input_limit", [(1, 5000), (40, 5000), (40, 64000)])
async def test_response_schema_reserve_covers_sdk_reference_expansion(
    references, input_limit, monkeypatch
):
    from eneo.completion_models.infrastructure.adapters.base_adapter import (
        ProviderInput,
    )
    from eneo.completion_models.infrastructure.context_builder import (
        ContextWindowExceededError,
    )
    from eneo.tokens.token_utils import measure_provider_input_reserve

    adapter = _make_adapter("anthropic", token_limit=input_limit, max_output_tokens=64)
    adapter.litellm_model = "anthropic/claude-sonnet-4-6"
    messages = [{"role": "user", "content": "hello"}]
    adapter.prepare_provider_input = Mock(
        return_value=ProviderInput(messages=messages, tools=[], built_in_tools=[])
    )
    schema = {
        "type": "object",
        "properties": {
            f"field_{i}": {"$ref": "#/$defs/Item"} for i in range(references)
        },
        "$defs": {
            "Item": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "value " * 250}
                },
                "required": ["label"],
                "additionalProperties": False,
            }
        },
        "required": [f"field_{i}" for i in range(references)],
        "additionalProperties": False,
    }
    response_format = {
        "type": "json_schema",
        "json_schema": {"name": "result", "schema": schema},
    }
    requests = []
    observer = SimpleNamespace(started=AsyncMock(), completed=AsyncMock())

    async def capture_request(client, request, **kwargs):
        requests.append(json.loads(await request.aread()))
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "response-1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", capture_request)

    async def dispatch():
        return await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={"response_format": response_format},
            provider_call_observer=observer,
            api_base="https://provider.example/v1",
        )

    if references == 40 and input_limit == 5000:
        with pytest.raises(ContextWindowExceededError):
            await dispatch()
        assert requests == []
        observer.started.assert_not_awaited()
    else:
        assert (await dispatch()).text == "ok"
        assert len(requests) == 1
        outbound = requests[0]
        emitted_format = (
            outbound.get("output_format") or outbound["output_config"]["format"]
        )
        assert "$ref" not in json.dumps(emitted_format)
        emitted_reserve = measure_provider_input_reserve(
            messages, [], adapter.litellm_model, response_format=emitted_format
        ).tokens
        assert emitted_reserve + outbound["max_tokens"] <= input_limit
        assert outbound["max_tokens"] == 64
        if references == 40:
            assert emitted_reserve > 5000
