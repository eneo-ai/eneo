import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from litellm.exceptions import BadRequestError

from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)
from eneo.flows.enums import FlowStepPhase
from eneo.flows.runtime import step_deadline
from eneo.flows.runtime.step_deadline import StepDeadline, step_deadline_scope
from eneo.main.exceptions import (
    OpenAIException,
    ProviderCapabilityRejectedException,
    TypedIOValidationException,
)
from eneo.model_providers.domain.provider_call_observer import (
    ProviderCallObserverError,
)


class _FakeMCPProxy:
    def __init__(self):
        self.call_count = 0

    def get_allowed_tool_names(self):
        return {"server__tool"}

    def get_tool_info(self, prefixed_tool_name: str):
        return ("Server", "tool", None)

    def get_tool_purpose(self, prefixed_tool_name: str) -> str | None:
        del prefixed_tool_name
        return None

    async def call_tools_parallel(self, proxy_calls):
        self.call_count += 1
        return [{"content": [{"type": "text", "text": "ok"}], "is_error": False}]


def _make_adapter() -> TenantModelAdapter:
    adapter = object.__new__(TenantModelAdapter)
    adapter.litellm_model = "openai/test-model"
    adapter.model = SimpleNamespace(
        name="test-model", token_limit=8000, max_output_tokens=4000
    )
    adapter.provider_type = "openai"

    adapter._prepare_kwargs = lambda model_kwargs, **kwargs: {}
    adapter._create_messages_from_context = lambda context: []
    adapter._build_tools_from_context = lambda context: []
    adapter._merge_mcp_tools = lambda eneo_tools, mcp_proxy, skill_runtime=None: [
        {"type": "function"}
    ]
    adapter._get_dropped_params = lambda litellm_kwargs: set()
    adapter._get_effective_params = lambda litellm_kwargs, dropped: {}
    adapter._strip_thinking_content = lambda text: text
    return adapter


def _usage(
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    reasoning_tokens: int | None,
):
    return SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning_tokens),
    )


def _response(
    *,
    response_id: str,
    content: str | None = None,
    tool_calls: list[SimpleNamespace] | None = None,
    finish_reason: str = "stop",
    usage: SimpleNamespace | None = None,
):
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=tool_calls),
                finish_reason=finish_reason,
            )
        ],
        id=response_id,
        usage=usage,
    )
    return response


def _tool_call():
    return SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(
            name="server__tool",
            arguments='{"q":"hello"}',
        ),
    )


@pytest.mark.asyncio
async def test_get_response_executes_non_streaming_tool_round():
    adapter = _make_adapter()
    mcp_proxy = _FakeMCPProxy()

    first_response = _response(
        response_id="resp-initial",
        tool_calls=[_tool_call()],
        finish_reason="tool_calls",
    )
    follow_up_response = _response(
        response_id="resp-final",
        content="final answer",
    )

    mocked_acompletion = AsyncMock(side_effect=[first_response, follow_up_response])

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        mocked_acompletion,
    ):
        completion = await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            mcp_proxy=mcp_proxy,
        )

    assert completion.text == "final answer"
    assert completion.provider_response_id == "resp-final"
    assert mocked_acompletion.await_count == 2
    assert mcp_proxy.call_count == 1


@pytest.mark.asyncio
async def test_get_response_propagates_unknown_usage_dimensions_across_tool_round():
    adapter = _make_adapter()
    mcp_proxy = _FakeMCPProxy()
    first_response = _response(
        response_id="resp-initial",
        tool_calls=[_tool_call()],
        finish_reason="tool_calls",
        usage=_usage(
            prompt_tokens=10,
            completion_tokens=None,
            reasoning_tokens=0,
        ),
    )
    follow_up_response = _response(
        response_id="resp-final",
        content="final answer",
        usage=_usage(
            prompt_tokens=None,
            completion_tokens=4,
            reasoning_tokens=5,
        ),
    )

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(side_effect=[first_response, follow_up_response]),
    ):
        completion = await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            mcp_proxy=mcp_proxy,
        )

    assert completion.usage is not None
    assert completion.usage.prompt_tokens is None
    assert completion.usage.completion_tokens is None
    assert completion.usage.reasoning_tokens == 5


@pytest.mark.asyncio
async def test_get_response_missing_follow_up_usage_makes_aggregate_unknown():
    adapter = _make_adapter()
    mcp_proxy = _FakeMCPProxy()
    first_response = _response(
        response_id="resp-initial",
        tool_calls=[_tool_call()],
        finish_reason="tool_calls",
        usage=_usage(
            prompt_tokens=10,
            completion_tokens=4,
            reasoning_tokens=0,
        ),
    )
    follow_up_response = _response(
        response_id="resp-final",
        content="final answer",
    )

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(side_effect=[first_response, follow_up_response]),
    ):
        completion = await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            mcp_proxy=mcp_proxy,
        )

    assert completion.usage is not None
    assert completion.usage.prompt_tokens is None
    assert completion.usage.completion_tokens is None
    assert completion.usage.reasoning_tokens is None


@pytest.mark.asyncio
async def test_get_response_preserves_single_call_usage():
    adapter = _make_adapter()
    response = _response(
        response_id="resp-single",
        content="answer",
        usage=_usage(
            prompt_tokens=0,
            completion_tokens=4,
            reasoning_tokens=None,
        ),
    )

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(return_value=response),
    ):
        completion = await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
        )

    assert completion.usage is not None
    assert completion.usage.prompt_tokens == 0
    assert completion.usage.completion_tokens == 4
    assert completion.usage.reasoning_tokens is None


@pytest.mark.asyncio
async def test_late_capability_rejection_is_not_safe_to_repeat_without_capability():
    adapter = _make_adapter()
    mcp_proxy = _FakeMCPProxy()
    tool_call_message = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(
                    name="server__tool",
                    arguments='{"q":"hello"}',
                ),
            )
        ],
    )
    first_response = SimpleNamespace(
        choices=[
            SimpleNamespace(message=tool_call_message, finish_reason="tool_calls")
        ],
        id="resp-initial",
    )
    late_rejection = BadRequestError(
        message="unsupported request parameter",
        model="test-model",
        llm_provider="openai",
        body={
            "error": {
                "param": "response_format",
                "code": "unsupported_parameter",
            }
        },
    )
    mocked_acompletion = AsyncMock(side_effect=[first_response, late_rejection])

    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            mocked_acompletion,
        ),
        pytest.raises(ProviderCapabilityRejectedException) as exc_info,
    ):
        await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            mcp_proxy=mcp_proxy,
        )

    assert exc_info.value.retry_without_capability_safe is False
    assert mocked_acompletion.await_count == 2
    assert mcp_proxy.call_count == 1


@pytest.mark.asyncio
async def test_provider_call_observer_records_each_tool_round_separately():
    adapter = _make_adapter()
    mcp_proxy = _FakeMCPProxy()
    initial_call_id = uuid4()
    tool_round_call_id = uuid4()
    observer = SimpleNamespace(
        started=AsyncMock(side_effect=[initial_call_id, tool_round_call_id]),
        completed=AsyncMock(),
        rejected=AsyncMock(),
        outcome_unknown=AsyncMock(),
    )

    first_message = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(name="server__tool", arguments='{"q":"x"}'),
            )
        ],
    )
    first_response = SimpleNamespace(
        choices=[SimpleNamespace(message=first_message, finish_reason="tool_calls")],
        id="resp-initial",
    )
    follow_up_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="final answer", tool_calls=None),
                finish_reason="stop",
            )
        ],
        id="resp-final",
    )

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(side_effect=[first_response, follow_up_response]),
    ):
        await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            mcp_proxy=mcp_proxy,
            provider_call_observer=observer,
        )

    assert [call.args[0].reason for call in observer.started.await_args_list] == [
        "initial",
        "tool_round",
    ]
    assert [
        call.args[0].requested_capabilities for call in observer.started.await_args_list
    ] == [
        ("tool_calling",),
        ("tool_calling",),
    ]
    assert [call.args[0] for call in observer.completed.await_args_list] == [
        initial_call_id,
        tool_round_call_id,
    ]
    assert [
        call.args[1].provider_response_id for call in observer.completed.await_args_list
    ] == [
        "resp-initial",
        "resp-final",
    ]


@pytest.mark.asyncio
async def test_provider_call_observer_wraps_actual_non_streaming_io():
    adapter = _make_adapter()
    call_id = uuid4()
    observer = SimpleNamespace(
        started=AsyncMock(return_value=call_id),
        completed=AsyncMock(),
        rejected=AsyncMock(),
        outcome_unknown=AsyncMock(),
    )
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="answer", tool_calls=None),
                finish_reason="stop",
            )
        ],
        id="observed-response",
        model="observed-model",
    )

    async def observed_provider_call(**_kwargs):
        observer.started.assert_awaited_once()
        return response

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(side_effect=observed_provider_call),
    ) as completion_call:
        await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            provider_call_observer=observer,
        )

    assert completion_call.await_count == 1
    request = observer.started.await_args.args[0]
    assert request.request_schema_version == 2
    assert request.requested_model == "openai/test-model"
    assert request.provider == "openai"
    assert request.provider_request_hash is not None
    observer.completed.assert_awaited_once()
    assert observer.completed.await_args.args[0] == call_id
    result = observer.completed.await_args.args[1]
    assert result.provider_response_id == "observed-response"
    assert result.response_model == "observed-model"
    observer.rejected.assert_not_awaited()
    observer.outcome_unknown.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("completed_calls", [0, 1])
async def test_budget_refusal_preserves_typed_error_and_rejects_unsent_receipt(
    monkeypatch, completed_calls
):
    adapter = _make_adapter()
    clock = {"now": 0.0}
    monkeypatch.setattr(step_deadline, "_now", lambda: clock["now"])
    call_ids = []

    async def started(request):
        if len(call_ids) == completed_calls:
            clock["now"] = 1.0
        call_ids.append(uuid4())
        return call_ids[-1]

    observer = SimpleNamespace(
        started=AsyncMock(side_effect=started),
        completed=AsyncMock(),
        rejected=AsyncMock(),
        outcome_unknown=AsyncMock(),
    )
    response = _response(
        response_id="initial",
        tool_calls=[_tool_call()],
        finish_reason="tool_calls",
    )
    with (
        patch(
            "eneo.model_providers.infrastructure.litellm_transport.litellm.acompletion",
            AsyncMock(return_value=response),
        ) as request,
        step_deadline_scope(StepDeadline.start(1), step_order=1) as scope,
    ):
        scope.phase = FlowStepPhase.PROVIDER_REQUEST
        with pytest.raises(TypedIOValidationException) as exc_info:
            await adapter.get_response(
                context=SimpleNamespace(),
                model_kwargs={},
                mcp_proxy=_FakeMCPProxy(),
                provider_call_observer=observer,
            )

    assert exc_info.value.code == "flow_step_timeout"
    assert exc_info.value.step_phase is FlowStepPhase.PROVIDER_REQUEST
    assert request.await_count == completed_calls
    assert observer.started.await_count == completed_calls + 1
    assert observer.completed.await_count == completed_calls
    observer.rejected.assert_awaited_once_with(call_ids[-1], "budget_exhausted")
    observer.outcome_unknown.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_request_preserves_an_earlier_unknown_outcome(monkeypatch):
    adapter = _make_adapter()
    observer = SimpleNamespace(
        started=AsyncMock(side_effect=[uuid4(), uuid4()]),
        completed=AsyncMock(),
        rejected=AsyncMock(),
        outcome_unknown=AsyncMock(),
    )
    request_count = 0

    async def request(**kwargs):
        nonlocal request_count
        request_count += 1
        assert step_deadline.current_step_deadline_scope().provider_request_in_flight
        if request_count == 1:
            raise TimeoutError("Request timed out after dispatch")
        return _response(response_id="success", content="done")

    monkeypatch.setattr(
        "eneo.model_providers.infrastructure.litellm_transport.litellm.acompletion",
        request,
    )
    with step_deadline_scope(StepDeadline.start(30), step_order=1) as scope:
        with pytest.raises(OpenAIException):
            await adapter.get_response(
                context=SimpleNamespace(),
                model_kwargs={},
                provider_call_observer=observer,
            )
        await adapter.get_response(
            context=SimpleNamespace(), model_kwargs={}, provider_call_observer=observer
        )
        assert scope.provider_request_in_flight is False
        assert (
            scope.deadline.timeout_error(
                step_order=1, phase="finalization"
            ).provider_work_may_have_completed
            is True
        )
    observer.outcome_unknown.assert_awaited_once()
    observer.completed.assert_awaited_once()
    assert request_count == 2


@pytest.mark.asyncio
async def test_provider_call_observer_records_known_capability_rejection():
    adapter = _make_adapter()
    call_id = uuid4()
    observer = SimpleNamespace(
        started=AsyncMock(return_value=call_id),
        completed=AsyncMock(),
        rejected=AsyncMock(),
        outcome_unknown=AsyncMock(),
    )
    rejection = BadRequestError(
        message="unsupported request parameter",
        model="test-model",
        llm_provider="openai",
        body={
            "error": {
                "param": "response_format",
                "code": "unsupported_parameter",
            }
        },
    )

    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            AsyncMock(side_effect=rejection),
        ),
        pytest.raises(ProviderCapabilityRejectedException),
    ):
        await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            provider_call_observer=observer,
        )

    observer.rejected.assert_awaited_once_with(call_id, "response_format_rejected")
    observer.completed.assert_not_awaited()
    observer.outcome_unknown.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_call_observer_start_failure_prevents_provider_io():
    adapter = _make_adapter()
    observer = SimpleNamespace(
        started=AsyncMock(
            side_effect=ProviderCallObserverError("evidence store unavailable")
        ),
        completed=AsyncMock(),
        rejected=AsyncMock(),
        outcome_unknown=AsyncMock(),
    )

    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            AsyncMock(),
        ) as completion_call,
        pytest.raises(ProviderCallObserverError, match="evidence store unavailable"),
    ):
        await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            provider_call_observer=observer,
        )

    completion_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_unserializable_request_evidence_prevents_provider_io():
    adapter = _make_adapter()
    adapter._prepare_kwargs = lambda model_kwargs, **kwargs: kwargs
    observer = SimpleNamespace(
        started=AsyncMock(),
        completed=AsyncMock(),
        rejected=AsyncMock(),
        outcome_unknown=AsyncMock(),
    )

    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            AsyncMock(),
        ) as completion_call,
        pytest.raises(
            ProviderCallObserverError,
            match="Provider request evidence could not be serialized safely",
        ),
    ):
        await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            provider_call_observer=observer,
            stop=object(),
        )

    observer.started.assert_not_awaited()
    completion_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_base_observer_error_from_completion_is_not_reported_as_pre_io():
    adapter = _make_adapter()
    provider_response = _response(response_id="provider-work-completed")
    observer = SimpleNamespace(
        started=AsyncMock(return_value=uuid4()),
        completed=AsyncMock(
            side_effect=ProviderCallObserverError("observer completed failed")
        ),
        rejected=AsyncMock(),
        outcome_unknown=AsyncMock(),
    )

    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            AsyncMock(return_value=provider_response),
        ) as completion_call,
        pytest.raises(OpenAIException) as exc_info,
    ):
        await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            provider_call_observer=observer,
        )

    completion_call.assert_awaited_once()
    observer.completed.assert_awaited_once()
    assert exc_info.value.code == "provider_error"


@pytest.mark.asyncio
@pytest.mark.parametrize("final_tool_count", [0, 1])
@pytest.mark.usefixtures("declared_capabilities")
async def test_each_tool_round_counts_results_and_the_refreshed_catalogue(
    final_tool_count,
):
    adapter = _make_adapter()
    adapter.model.max_output_tokens = 8000
    proxy = _FakeMCPProxy()
    proxy.refresh_tools = AsyncMock(return_value=True)
    adapter._merge_mcp_tools = lambda tools, mcp, skill_runtime=None: [
        {"type": "function", "function": {"name": "server__tool"}}
    ] * (
        10
        if proxy.call_count == 1
        else (final_tool_count if proxy.call_count > 1 else 1)
    )
    observed_inputs = []

    def reserve(messages, tools, model, *, response_format=None):
        result_count = sum(message["role"] == "tool" for message in messages)
        observed_inputs.append((result_count, len(tools)))
        return SimpleNamespace(tokens=10 + 20 * len(tools) + 50 * result_count)

    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter.measure_provider_input_reserve",
            side_effect=reserve,
        ),
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            AsyncMock(
                side_effect=[
                    _response(
                        response_id="first",
                        tool_calls=[_tool_call()],
                        finish_reason="tool_calls",
                    ),
                    _response(
                        response_id="second",
                        tool_calls=[_tool_call()],
                        finish_reason="tool_calls",
                    ),
                    _response(response_id="final", content="done"),
                ]
            ),
        ) as transport,
    ):
        await adapter.get_response(
            context=SimpleNamespace(), model_kwargs={}, mcp_proxy=proxy
        )
    assert observed_inputs == [(0, 1), (1, 10), (2, final_tool_count)]
    assert [call.kwargs["max_tokens"] for call in transport.await_args_list] == [
        7970,
        7740,
        7890 - 20 * final_tool_count,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["length", "stop", "tool_calls", None])
@pytest.mark.usefixtures("declared_capabilities")
async def test_completion_preserves_provider_finish_reason(finish_reason):
    adapter = _make_adapter()
    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(
            return_value=_response(
                response_id="response-1", content="answer", finish_reason=finish_reason
            )
        ),
    ):
        completion = await adapter.get_response(
            context=SimpleNamespace(), model_kwargs={}
        )
    assert completion.finish_reason == finish_reason
    assert completion.stop is (finish_reason == "stop")


@pytest.mark.asyncio
@pytest.mark.usefixtures("declared_capabilities")
async def test_length_response_does_not_execute_incomplete_tool_calls():
    adapter = _make_adapter()
    mcp_proxy = _FakeMCPProxy()
    provider_call = AsyncMock(
        return_value=_response(
            response_id="response-1", tool_calls=[_tool_call()], finish_reason="length"
        )
    )
    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        provider_call,
    ):
        await adapter.get_response(
            context=SimpleNamespace(), model_kwargs={}, mcp_proxy=mcp_proxy
        )
    assert mcp_proxy.call_count == 0
    provider_call.assert_awaited_once()


@pytest.fixture
def declared_capabilities(monkeypatch):
    monkeypatch.setattr(
        "litellm.get_supported_openai_params",
        lambda **kwargs: ["max_tokens", "max_completion_tokens"],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("remaining_output", [31, 32])
@pytest.mark.usefixtures("declared_capabilities")
async def test_dispatch_requires_the_callers_useful_output_reserve(remaining_output):
    from eneo.completion_models.infrastructure.context_builder import (
        ContextWindowExceededError,
    )
    from eneo.tokens.token_utils import TokenCount, TokenCountSource

    adapter = _make_adapter()
    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter.measure_provider_input_reserve",
            return_value=TokenCount(
                tokens=8000 - remaining_output, source=TokenCountSource.LITELLM
            ),
        ),
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            AsyncMock(return_value=_response(response_id="fit", content="done")),
        ) as transport,
    ):
        if remaining_output < 32:
            with pytest.raises(ContextWindowExceededError):
                await adapter.get_response(
                    context=SimpleNamespace(),
                    model_kwargs={},
                    useful_output_reserve_tokens=32,
                )
            transport.assert_not_awaited()
        else:
            await adapter.get_response(
                context=SimpleNamespace(),
                model_kwargs={},
                useful_output_reserve_tokens=32,
            )
            transport.assert_awaited_once()
            assert transport.await_args.kwargs["max_tokens"] == 32
            assert "useful_output_reserve_tokens" not in transport.await_args.kwargs


def _preflight_service():
    from eneo.ai_models.completion_models.completion_model import CompletionModel
    from eneo.completion_models.infrastructure.completion_service import (
        CompletionService,
    )
    from eneo.completion_models.infrastructure.context_builder import ContextBuilder

    now = datetime.now(timezone.utc)
    model = CompletionModel(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="gpt-4o-mini",
        nickname="test",
        family="openai",
        max_input_tokens=8000,
        max_output_tokens=4000,
        is_deprecated=False,
        stability="stable",
        hosting="eu",
        vision=False,
        reasoning=False,
        supports_tool_calling=True,
        is_org_enabled=True,
        is_org_default=False,
        tenant_id=uuid4(),
        provider_id=uuid4(),
    )
    adapter = _make_adapter()
    adapter.model = model
    adapter.litellm_model = "openai/gpt-4o-mini"
    for method in (
        "_create_messages_from_context",
        "_build_tools_from_context",
        "_merge_mcp_tools",
    ):
        delattr(adapter, method)
    adapter._prepare_kwargs = lambda model_kwargs, **kwargs: {
        **(model_kwargs.model_dump(exclude_none=True) if model_kwargs else {}),
        **kwargs,
    }
    service = CompletionService(context_builder=ContextBuilder())
    service._get_adapter = AsyncMock(return_value=adapter)
    return service, adapter, model


def _wire_payload(messages, tools, response_format):
    return json.dumps(
        {"messages": messages, "tools": tools, "response_format": response_format},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "package_case", ["plain", "attachments", "retrieved", "tools", "native", "fallback"]
)
@pytest.mark.usefixtures("declared_capabilities")
async def test_service_preflight_measures_the_outgoing_package(package_case):
    from eneo.ai_models.completion_models.completion_model import ModelKwargs
    from eneo.authentication.principal_types import PrincipalType
    from eneo.files.file_models import File, FileType
    from eneo.info_blobs.info_blob import InfoBlobChunkInDBWithScore
    from eneo.tokens.token_utils import measure_provider_input_reserve

    service, _, model = _preflight_service()
    now = datetime.now(timezone.utc)
    request = {
        "model": model,
        "text_input": "Summarize the source.",
        "prompt": "Be concise.",
        "version": 2,
    }
    if package_case == "attachments":
        request["prompt_files"] = [
            File(
                id=uuid4(),
                created_at=now,
                updated_at=now,
                name="guide.txt",
                checksum="test",
                size=20,
                file_type=FileType.TEXT,
                text="Attachment marker.",
                owner_type=PrincipalType.USER,
                tenant_id=uuid4(),
            )
        ]
    if package_case == "retrieved":
        request["info_blob_chunks"] = [
            InfoBlobChunkInDBWithScore(
                id=uuid4(),
                created_at=now,
                updated_at=now,
                text="Retrieved marker.",
                chunk_no=0,
                info_blob_id=uuid4(),
                tenant_id=uuid4(),
                info_blob_title="Retrieved source",
                score=0.9,
            )
        ]
    proxy = None
    if package_case == "tools":
        tool = {
            "type": "function",
            "function": {
                "name": "server__lookup",
                "description": "Find source",
                "parameters": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                },
            },
        }
        proxy = SimpleNamespace(
            get_tools_for_llm=lambda: [tool],
            get_tool_count=lambda: 1,
            get_allowed_tool_names=lambda: {"server__lookup"},
            prepare_tools_for_context=AsyncMock(),
            close=AsyncMock(),
        )
        service._mcp_proxy_factory = SimpleNamespace(
            create=lambda *args, **kwargs: proxy
        )
    fallback_prompt = None
    if package_case in {"native", "fallback"}:
        request["model_kwargs"] = ModelKwargs(
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "answer",
                    "schema": {
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                        "additionalProperties": False,
                    },
                },
            }
        )
        fallback_prompt = 'Be concise.\nReturn JSON matching {"answer": "string"}.'
    measured = []

    def measure(messages, tools, route, *, response_format=None):
        measured.append(_wire_payload(messages, tools, response_format))
        return measure_provider_input_reserve(
            messages, tools, route, response_format=response_format
        )

    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter.measure_provider_input_reserve",
            side_effect=measure,
        ),
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            AsyncMock(return_value=_response(response_id="measured", content="done")),
        ) as transport,
    ):
        result = await service.preflight_request(
            **request,
            mcp_proxy=proxy,
            capability_fallback_prompt=fallback_prompt,
            useful_output_reserve_tokens=32,
        )
        transport.assert_not_awaited()
        package = result.fallback if package_case == "fallback" else result.preferred
        assert package.fits
        assert result.refusal is None
        assert result.retrieval_included is (package_case == "retrieved")
        expected = _wire_payload(
            package.messages, package.tools, package.response_format
        )
        assert expected in measured
        if package_case == "fallback":
            request["prompt"] = fallback_prompt
            request["model_kwargs"] = ModelKwargs()
        if proxy is not None:
            request["mcp_servers"] = [SimpleNamespace(is_enabled=True)]
        await service.get_response(**request, useful_output_reserve_tokens=32)
    transport.assert_awaited_once()
    sent = transport.await_args.kwargs
    assert (
        _wire_payload(
            sent["messages"], sent.get("tools", []), sent.get("response_format")
        )
        == expected
    )
    assert measured[-1] == expected
    assert sent["max_tokens"] == package.output_cap_tokens
    if package_case == "attachments":
        assert b"Attachment marker." in expected
    if package_case == "retrieved":
        assert b"Retrieved marker." in expected
        assert b"source_title: Retrieved source" in expected
    if proxy is not None:
        assert proxy.prepare_tools_for_context.await_count == 1


@pytest.mark.asyncio
async def test_preflight_requires_the_dispatch_fallback_prompt_for_native_schema():
    from eneo.ai_models.completion_models.completion_model import ModelKwargs

    service, _, model = _preflight_service()
    with pytest.raises(ValueError, match="fallback prompt"):
        await service.preflight_request(
            model=model,
            text_input="hi",
            model_kwargs=ModelKwargs(
                response_format={
                    "type": "json_schema",
                    "json_schema": {"schema": {"type": "object"}},
                }
            ),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "preferred_tokens,fallback_tokens,output_limit,refusal",
    [
        (7969, 7968, 4000, None),
        (7968, 7969, 4000, None),
        (7969, 7969, 4000, "smallest_admissible_input_cannot_fit"),
        (100, 100, 31, "fixed_overhead_too_large"),
    ],
)
@pytest.mark.usefixtures("declared_capabilities")
async def test_preflight_fit_matches_dispatch_for_each_package(
    preferred_tokens, fallback_tokens, output_limit, refusal
):
    from eneo.ai_models.completion_models.completion_model import ModelKwargs
    from eneo.completion_models.infrastructure.context_builder import (
        ContextWindowExceededError,
    )
    from eneo.tokens.token_utils import TokenCount, TokenCountSource

    service, _, model = _preflight_service()
    model.max_output_tokens = output_limit
    kwargs = ModelKwargs(response_format={"type": "json_object"})

    def measure(messages, tools, route, *, response_format=None):
        return TokenCount(
            tokens=preferred_tokens if response_format else fallback_tokens,
            source=TokenCountSource.LITELLM,
        )

    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter.measure_provider_input_reserve",
            side_effect=measure,
        ),
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            AsyncMock(return_value=_response(response_id="fit", content="done")),
        ) as transport,
    ):
        result = await service.preflight_request(
            model=model,
            text_input="Source",
            prompt="Return JSON",
            model_kwargs=kwargs,
            capability_fallback_prompt="Return JSON",
            useful_output_reserve_tokens=32,
        )
        transport.assert_not_awaited()
        assert result.refusal == refusal
        assert result.model_route == "openai/gpt-4o-mini"
        assert result.capacity.max_input_tokens == 8000
        for package, model_kwargs in [
            (result.preferred, kwargs),
            (result.fallback, ModelKwargs()),
        ]:
            assert package.fits is (
                min(8000 - package.input_reserve.tokens, output_limit) >= 32
            )
            if package.fits:
                await service.get_response(
                    model=model,
                    text_input="Source",
                    prompt="Return JSON",
                    model_kwargs=model_kwargs,
                    useful_output_reserve_tokens=32,
                )
                assert transport.await_args.kwargs["max_tokens"] == 32
            else:
                prior_calls = transport.await_count
                with pytest.raises(ContextWindowExceededError):
                    await service.get_response(
                        model=model,
                        text_input="Source",
                        prompt="Return JSON",
                        model_kwargs=model_kwargs,
                        useful_output_reserve_tokens=32,
                    )
                assert transport.await_count == prior_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("counter_available", [True, False])
async def test_preflight_reports_counter_provenance_and_admits_a_fitting_byte_bound(
    counter_available, monkeypatch
):
    from eneo.tokens.token_utils import TokenCountSource

    service, adapter, model = _preflight_service()
    if not counter_available:
        adapter.litellm_model = "unknown/no-tokenizer"

        def unavailable(**kwargs):
            raise ValueError("No tokenizer for this route")

        monkeypatch.setattr("litellm.token_counter", unavailable)
    result = await service.preflight_request(
        model=model, text_input="Source", useful_output_reserve_tokens=32
    )
    assert result.preferred.fits
    assert result.refusal is None
    assert result.preferred.input_reserve.source is (
        TokenCountSource.LITELLM
        if counter_available
        else TokenCountSource.FALLBACK_ESTIMATE
    )
    assert result.preferred.input_reserve.tokens > 0
    assert result.retrieval_included is False


@pytest.mark.asyncio
@pytest.mark.usefixtures("declared_capabilities")
async def test_stream_preparation_sends_the_measured_package_and_useful_cap():
    service, adapter, model = _preflight_service()
    evidence = await service.preflight_request(
        model=model,
        text_input="Source",
        prompt="Explain.",
        useful_output_reserve_tokens=32,
    )
    context = service.context_builder.build_context(
        input_str="Source",
        prompt="Explain.",
        max_tokens=8000,
        model_name=adapter.litellm_model,
        vision=False,
    )
    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(return_value=SimpleNamespace()),
    ) as transport:
        await adapter.prepare_streaming(
            context=context, useful_output_reserve_tokens=32
        )
    sent = transport.await_args.kwargs
    assert _wire_payload(
        sent["messages"], sent.get("tools", []), sent.get("response_format")
    ) == _wire_payload(
        evidence.preferred.messages,
        evidence.preferred.tools,
        evidence.preferred.response_format,
    )
    assert sent["max_tokens"] == evidence.preferred.output_cap_tokens
    assert "useful_output_reserve_tokens" not in sent
