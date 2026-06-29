from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import httpx
import pytest

from intric.ai_models.completion_models.completion_model import ResponseType
from intric.completion_models.infrastructure.adapters.tenant_model_adapter import (
    PROVIDER_UNAVAILABLE_CODE,
    PROVIDER_UNAVAILABLE_MESSAGE,
    PreparedModelStream,
    TenantModelAdapter,
    _build_tool_result_with_references,
)
from intric.main.exceptions import OpenAIException
from intric.mcp_servers.infrastructure.tool_approval import (
    ToolApprovalDecision,
    ToolApprovalWaitResult,
)


class _AsyncChunkStream:
    def __init__(self, chunks, eneo_context=None):
        self._chunks = list(chunks)
        if eneo_context is not None:
            self._eneo_context = eneo_context

    def __aiter__(self):
        self._iter = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


def _tool_call_chunk(
    *,
    tool_call_id: str = "call_1",
    tool_name: str = "server__tool",
    arguments: str = '{"q":"x"}',
):
    delta = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                index=0,
                id=tool_call_id,
                function=SimpleNamespace(name=tool_name, arguments=arguments),
            )
        ],
    )
    choice = SimpleNamespace(delta=delta, finish_reason="tool_calls")
    return SimpleNamespace(choices=[choice])


def _tool_call_delta_chunk(
    *,
    index: int = 0,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
    arguments: str | None = None,
    finish_reason: str | None = None,
):
    delta = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                index=index,
                id=tool_call_id,
                function=SimpleNamespace(name=tool_name, arguments=arguments),
            )
        ],
    )
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def _text_chunk(text: str, finish_reason: str | None = None):
    delta = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def _response(*, content=None, tool_calls=None, finish_reason="stop"):
    message = SimpleNamespace(
        content=content,
        reasoning_content=None,
        tool_calls=tool_calls,
    )
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=None)


def _response_tool_call(tool_call_id: str, arguments: str):
    return SimpleNamespace(
        id=tool_call_id,
        function=SimpleNamespace(name="server__tool", arguments=arguments),
    )


class _FakeMCPProxy:
    def __init__(self):
        self.calls = []

    def get_allowed_tool_names(self):
        return {"server__tool"}

    def get_tool_info(self, prefixed_tool_name: str):
        return ("Server", "tool", "Tool title")

    async def call_tools_parallel(self, proxy_calls):
        self.calls.append(proxy_calls)
        return [
            {"content": [{"type": "text", "text": "tool-ok"}], "is_error": False}
            for _ in proxy_calls
        ]


class _ResourceMCPProxy(_FakeMCPProxy):
    async def call_tools_parallel(self, proxy_calls):
        self.calls.append(proxy_calls)
        call_number = len(self.calls)
        return [
            {
                "content": [
                    {
                        "type": "resource",
                        "uri": "https://example.test/shared",
                        "mime_type": "text/plain",
                        "text": f"resource round {call_number}",
                        "meta": {},
                    }
                ],
                "is_error": False,
            }
            for _ in proxy_calls
        ]


def _make_adapter() -> TenantModelAdapter:
    adapter = object.__new__(TenantModelAdapter)
    adapter.litellm_model = "openai/test-model"
    adapter.provider_type = "openai"
    adapter.model = SimpleNamespace(name="test-model")
    return adapter


def test_build_tool_result_with_references_uses_self_describing_resource_blocks():
    llm_text, display_text, refs = _build_tool_result_with_references(
        content_list=[
            {"type": "text", "text": "Tool summary.\n"},
            {
                "type": "resource",
                "uri": "https://example.test/docs/alpha",
                "mime_type": "text/markdown",
                "text": "**Alpha document** — Intro\n\nResource body",
                "meta": {
                    "title": "Alpha document",
                    "pageRange": "3-4",
                    "customKey": {"nested": True},
                },
            },
        ],
        tool_call_id="call_1",
        mcp_tool_name="server__tool",
        existing_prefixes=set(),
    )

    # Resource fields (uri/mime/content/meta) are persisted for the UI channel.
    assert len(refs) == 1
    source_id = str(refs[0].id)[:8]
    assert refs[0].uri == "https://example.test/docs/alpha"
    assert refs[0].mime_type == "text/markdown"
    assert refs[0].content == "**Alpha document** — Intro\n\nResource body"
    assert refs[0].meta["customKey"] == {"nested": True}

    # display_text mirrors a vanilla client: upstream text + the resource's own
    # text, no source_id markers.
    assert (
        display_text == "Tool summary.\n\n**Alpha document** — Intro\n\nResource body"
    )

    # Model channel: each resource is a self-describing, triple-quoted block whose
    # attribution rides in the server text; Eneo prepends only the source_id.
    assert (
        f'"""source_id: {source_id}\n**Alpha document** — Intro\n\nResource body"""'
        in llm_text
    )
    assert "Tool summary." in llm_text
    assert '<inref id="<source_id>"/>' in llm_text

    # No standalone JSON index, and _meta is not forwarded to the model.
    assert "MCP referenced resources:" not in llm_text
    assert '"metadata"' not in llm_text
    assert '"uri"' not in llm_text
    assert "pageRange" not in llm_text
    assert "customKey" not in llm_text


def test_build_tool_result_with_references_skips_unciteable_resources():
    llm_text, display_text, refs = _build_tool_result_with_references(
        content_list=[
            {"type": "text", "text": "Tool summary."},
            {
                "type": "resource",
                "text": "No URI",
                "meta": {"title": "Cannot cite"},
            },
        ],
        tool_call_id="call_1",
        mcp_tool_name="server__tool",
        existing_prefixes=set(),
    )

    assert display_text == "Tool summary."
    assert llm_text == "Tool summary."
    assert refs == []


def _make_completion_adapter() -> TenantModelAdapter:
    adapter = _make_adapter()
    adapter._prepare_kwargs = Mock(return_value={})
    adapter._create_messages_from_context = Mock(
        return_value=[{"role": "user", "content": "hello"}]
    )
    adapter._build_tools_from_context = Mock(return_value=[])
    adapter._merge_mcp_tools = Mock(return_value=[])
    adapter._get_dropped_params = Mock(return_value=set())
    adapter._get_effective_params = Mock(return_value={})
    return adapter


async def _collect(adapter: TenantModelAdapter, stream, **kwargs):
    eneo_context = getattr(stream, "_eneo_context", None)
    if eneo_context is not None:
        stream = PreparedModelStream(
            stream=stream,
            messages=eneo_context["messages"],
            kwargs=eneo_context["kwargs"],
            mcp_proxy=eneo_context["mcp_proxy"],
            has_tools=eneo_context["has_tools"],
        )
    output = []
    async for chunk in adapter.iterate_stream(
        stream=stream,
        context=None,
        model_kwargs={},
        **kwargs,
    ):
        output.append(chunk)
    return output


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "phase"),
    [
        ("get_response", "completion"),
        ("prepare_streaming", "stream_preparation"),
    ],
)
async def test_provider_connectivity_failure_returns_clear_unavailable_error(
    method_name: str,
    phase: str,
):
    adapter = _make_completion_adapter()
    span = Mock()
    span.is_recording.return_value = True

    with (
        patch(
            "intric.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            AsyncMock(
                side_effect=httpx.ConnectError("Temporary failure in name resolution")
            ),
        ),
        patch(
            "intric.completion_models.infrastructure.adapters.tenant_model_adapter.trace.get_current_span",
            return_value=span,
        ),
    ):
        with pytest.raises(OpenAIException) as exc_info:
            if method_name == "get_response":
                await adapter.get_response(context=SimpleNamespace(), model_kwargs={})
            else:
                await adapter.prepare_streaming(
                    context=SimpleNamespace(), model_kwargs={}
                )

    exc = exc_info.value
    assert str(exc) == PROVIDER_UNAVAILABLE_MESSAGE
    assert exc.code == PROVIDER_UNAVAILABLE_CODE
    assert exc.details == {"reason": PROVIDER_UNAVAILABLE_CODE, "retryable": True}
    span.set_attribute.assert_any_call("gen_ai.operation.name", "chat")
    span.set_attribute.assert_any_call("gen_ai.provider.name", "openai")
    span.set_attribute.assert_any_call("gen_ai.request.model", "test-model")
    span.set_attribute.assert_any_call(
        "gen_ai.request.stream", method_name == "prepare_streaming"
    )
    span.set_attribute.assert_any_call("error.type", PROVIDER_UNAVAILABLE_CODE)
    span.set_attribute.assert_any_call("eneo.ai.provider_unavailable", True)
    span.set_attribute.assert_any_call("eneo.ai.operation", phase)
    span.record_exception.assert_called_once()


@pytest.mark.asyncio
async def test_wrapped_provider_failure_returns_clear_unavailable_error():
    adapter = _make_completion_adapter()
    outer_error = RuntimeError("upstream call failed")
    outer_error.__cause__ = httpx.ConnectError("Temporary failure in name resolution")

    with patch(
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(side_effect=outer_error),
    ):
        with pytest.raises(OpenAIException) as exc_info:
            await adapter.get_response(context=SimpleNamespace(), model_kwargs={})

    exc = exc_info.value
    assert str(exc) == PROVIDER_UNAVAILABLE_MESSAGE
    assert exc.code == PROVIDER_UNAVAILABLE_CODE
    assert exc.details == {"reason": PROVIDER_UNAVAILABLE_CODE, "retryable": True}


@pytest.mark.asyncio
async def test_text_only_provider_failure_returns_clear_unavailable_error():
    adapter = _make_completion_adapter()

    with patch(
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(side_effect=RuntimeError("Connection refused by upstream")),
    ):
        with pytest.raises(OpenAIException) as exc_info:
            await adapter.get_response(context=SimpleNamespace(), model_kwargs={})

    exc = exc_info.value
    assert str(exc) == PROVIDER_UNAVAILABLE_MESSAGE
    assert exc.code == PROVIDER_UNAVAILABLE_CODE
    assert exc.details == {"reason": PROVIDER_UNAVAILABLE_CODE, "retryable": True}


@pytest.mark.asyncio
async def test_unknown_stream_preparation_error_remains_unexpected():
    adapter = _make_completion_adapter()

    with patch(
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        with pytest.raises(OpenAIException) as exc_info:
            await adapter.prepare_streaming(context=SimpleNamespace(), model_kwargs={})

    assert str(exc_info.value) == (
        "The AI provider could not process the request. Please try again later."
    )
    assert exc_info.value.code == "provider_error"


@pytest.mark.asyncio
async def test_generic_timeout_word_remains_unexpected():
    adapter = _make_completion_adapter()

    with patch(
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(side_effect=RuntimeError("provider timeout budget exceeded")),
    ):
        with pytest.raises(OpenAIException) as exc_info:
            await adapter.prepare_streaming(context=SimpleNamespace(), model_kwargs={})

    assert str(exc_info.value) == (
        "The AI provider could not process the request. Please try again later."
    )
    assert exc_info.value.code == "provider_error"


@pytest.mark.asyncio
async def test_prepare_streaming_returns_explicit_context_wrapper():
    adapter = _make_completion_adapter()
    raw_stream = _AsyncChunkStream([_text_chunk("done", finish_reason="stop")])

    with patch(
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(return_value=raw_stream),
    ):
        prepared = await adapter.prepare_streaming(
            context=SimpleNamespace(),
            model_kwargs={},
        )

    assert isinstance(prepared, PreparedModelStream)
    assert prepared.stream is raw_stream
    assert prepared.messages == [{"role": "user", "content": "hello"}]
    assert not hasattr(raw_stream, "_eneo_context")


@pytest.mark.asyncio
async def test_non_streaming_supports_multiple_tool_rounds():
    adapter = _make_completion_adapter()
    mcp_proxy = _ResourceMCPProxy()
    responses = [
        _response(
            tool_calls=[_response_tool_call("call_1", '{"q":"first"}')],
            finish_reason="tool_calls",
        ),
        _response(
            tool_calls=[_response_tool_call("call_2", '{"q":"second"}')],
            finish_reason="tool_calls",
        ),
        _response(content="final answer"),
    ]

    with patch(
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(side_effect=responses),
    ) as completion_call:
        completion = await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            mcp_proxy=mcp_proxy,
        )

    assert completion.text == "final answer"
    assert completion.stop is True
    assert completion_call.await_count == 3
    assert mcp_proxy.calls == [
        [("server__tool", {"q": "first"})],
        [("server__tool", {"q": "second"})],
    ]
    assert completion.mcp_tool_references is not None
    assert len(completion.mcp_tool_references) == 2
    assert {ref.tool_call_id for ref in completion.mcp_tool_references} == {
        "call_1",
        "call_2",
    }
    assert {ref.uri for ref in completion.mcp_tool_references} == {
        "https://example.test/shared"
    }


def test_models_without_tool_capability_receive_no_tools():
    adapter = _make_adapter()
    adapter.model.supports_tool_calling = False

    assert adapter._merge_mcp_tools([{"type": "function"}], _FakeMCPProxy()) == []


@pytest.mark.asyncio
async def test_mid_stream_provider_failure_yields_unavailable_event():
    adapter = _make_adapter()
    mcp_proxy = _FakeMCPProxy()
    span = Mock()
    span.is_recording.return_value = True

    stream = _AsyncChunkStream(
        [_tool_call_chunk()],
        eneo_context={
            "mcp_proxy": mcp_proxy,
            "messages": [],
            "kwargs": {},
            "has_tools": True,
        },
    )

    with (
        patch(
            "intric.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            AsyncMock(side_effect=httpx.ConnectError("Connection refused")),
        ),
        patch(
            "intric.completion_models.infrastructure.adapters.tenant_model_adapter.trace.get_current_span",
            return_value=span,
        ),
    ):
        completions = await _collect(
            adapter,
            stream,
            require_tool_approval=False,
            approval_manager=None,
            approval_context=None,
            pending_approval_ids=set(),
        )

    errors = [c for c in completions if c.response_type == ResponseType.ERROR]
    assert len(errors) == 1
    assert errors[0].error == PROVIDER_UNAVAILABLE_MESSAGE
    assert errors[0].error_code == 503
    span.set_attribute.assert_any_call("gen_ai.request.stream", True)
    span.set_attribute.assert_any_call("error.type", PROVIDER_UNAVAILABLE_CODE)


def _tool_call_events(completions):
    return [
        c
        for c in completions
        if c.response_type == ResponseType.TOOL_CALL and c.tool_calls_metadata
    ]


@pytest.mark.asyncio
async def test_iterate_stream_emits_pending_event_before_arguments_complete():
    adapter = _make_adapter()
    mcp_proxy = _FakeMCPProxy()
    follow_up_stream = _AsyncChunkStream([_text_chunk("done", finish_reason="stop")])
    mocked_acompletion = AsyncMock(return_value=follow_up_stream)

    stream = _AsyncChunkStream(
        [
            _tool_call_delta_chunk(tool_call_id="call_1", tool_name="server__tool"),
            _tool_call_delta_chunk(arguments='{"q":'),
            _tool_call_delta_chunk(arguments='"x"}', finish_reason="tool_calls"),
        ],
        eneo_context={
            "mcp_proxy": mcp_proxy,
            "messages": [],
            "kwargs": {},
            "has_tools": True,
        },
    )

    with patch(
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        mocked_acompletion,
    ):
        completions = await _collect(
            adapter,
            stream,
            require_tool_approval=False,
            approval_manager=None,
            approval_context=None,
            pending_approval_ids=set(),
        )

    tool_events = _tool_call_events(completions)
    pending = [
        e for e in tool_events if e.tool_calls_metadata[0].result_status == "pending"
    ]
    assert len(pending) == 1
    meta = pending[0].tool_calls_metadata[0]
    assert meta.tool_call_id == "call_1"
    assert meta.server_name == "Server"
    assert meta.tool_name == "tool"
    assert meta.arguments is None
    assert meta.mcp_tool_name == "server__tool"

    # Pending must precede the approved/executed events for the same call
    statuses = [e.tool_calls_metadata[0].result_status for e in tool_events]
    assert statuses[0] == "pending"
    assert "succeeded" in statuses


@pytest.mark.asyncio
async def test_iterate_stream_emits_pending_per_parallel_tool_call():
    adapter = _make_adapter()
    mcp_proxy = _FakeMCPProxy()
    follow_up_stream = _AsyncChunkStream([_text_chunk("done", finish_reason="stop")])
    mocked_acompletion = AsyncMock(return_value=follow_up_stream)

    stream = _AsyncChunkStream(
        [
            _tool_call_delta_chunk(
                index=0, tool_call_id="call_1", tool_name="server__tool"
            ),
            _tool_call_delta_chunk(index=0, arguments='{"q":"a"}'),
            _tool_call_delta_chunk(
                index=1, tool_call_id="call_2", tool_name="server__tool"
            ),
            _tool_call_delta_chunk(
                index=1, arguments='{"q":"b"}', finish_reason="tool_calls"
            ),
        ],
        eneo_context={
            "mcp_proxy": mcp_proxy,
            "messages": [],
            "kwargs": {},
            "has_tools": True,
        },
    )

    with patch(
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        mocked_acompletion,
    ):
        completions = await _collect(
            adapter,
            stream,
            require_tool_approval=False,
            approval_manager=None,
            approval_context=None,
            pending_approval_ids=set(),
        )

    pending_ids = [
        e.tool_calls_metadata[0].tool_call_id
        for e in _tool_call_events(completions)
        if e.tool_calls_metadata[0].result_status == "pending"
    ]
    assert pending_ids == ["call_1", "call_2"]
    assert mcp_proxy.calls == [
        [("server__tool", {"q": "a"}), ("server__tool", {"q": "b"})]
    ]


@pytest.mark.asyncio
async def test_iterate_stream_no_pending_event_for_disallowed_tool():
    adapter = _make_adapter()
    mcp_proxy = _FakeMCPProxy()

    stream = _AsyncChunkStream(
        [
            _tool_call_delta_chunk(
                tool_call_id="call_1",
                tool_name="server__forbidden",
                arguments="{}",
                finish_reason="tool_calls",
            ),
        ],
        eneo_context={
            "mcp_proxy": mcp_proxy,
            "messages": [],
            "kwargs": {},
            "has_tools": True,
        },
    )

    completions = await _collect(
        adapter,
        stream,
        require_tool_approval=False,
        approval_manager=None,
        approval_context=None,
        pending_approval_ids=set(),
    )

    assert not _tool_call_events(completions)
    assert any(c.response_type == ResponseType.ERROR for c in completions)


@pytest.mark.asyncio
async def test_iterate_stream_stops_at_max_rounds():
    adapter = _make_adapter()
    mcp_proxy = _FakeMCPProxy()

    # Follow-up always returns another tool call to force round cap.
    async def _next_stream(*args, **kwargs):
        return _AsyncChunkStream([_tool_call_chunk()])

    mocked_acompletion = AsyncMock(side_effect=_next_stream)

    stream = _AsyncChunkStream(
        [_tool_call_chunk()],
        eneo_context={
            "mcp_proxy": mcp_proxy,
            "messages": [],
            "kwargs": {},
            "has_tools": True,
        },
    )

    with patch(
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        mocked_acompletion,
    ):
        completions = await _collect(
            adapter,
            stream,
            require_tool_approval=False,
            approval_manager=None,
            approval_context=None,
            pending_approval_ids=set(),
        )

    assert mocked_acompletion.await_count == 10
    assert any(chunk.stop for chunk in completions)


@pytest.mark.asyncio
async def test_iterate_stream_yields_approval_required_and_blocks():
    adapter = _make_adapter()
    mcp_proxy = _FakeMCPProxy()
    approval_manager = AsyncMock()

    approval_manager.wait_for_approval.return_value = ToolApprovalWaitResult(
        decisions=[ToolApprovalDecision(tool_call_id="call_1", approved=True)],
        timed_out=False,
    )
    follow_up_stream = _AsyncChunkStream([_text_chunk("done", finish_reason="stop")])
    mocked_acompletion = AsyncMock(return_value=follow_up_stream)

    stream = _AsyncChunkStream(
        [_tool_call_chunk()],
        eneo_context={
            "mcp_proxy": mcp_proxy,
            "messages": [],
            "kwargs": {},
            "has_tools": True,
        },
    )

    with patch(
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        mocked_acompletion,
    ):
        completions = await _collect(
            adapter,
            stream,
            require_tool_approval=True,
            approval_manager=approval_manager,
            approval_context={
                "tenant_id": uuid4(),
                "user_id": uuid4(),
                "session_id": uuid4(),
                "assistant_id": uuid4(),
            },
            pending_approval_ids=set(),
        )

    assert any(
        c.response_type == ResponseType.TOOL_APPROVAL_REQUIRED for c in completions
    )
    approval_manager.request_approval.assert_awaited_once()
    approval_manager.wait_for_approval.assert_awaited_once()


@pytest.mark.asyncio
async def test_iterate_stream_timeout_yields_timeout_event_and_auto_denies():
    adapter = _make_adapter()
    mcp_proxy = _FakeMCPProxy()
    approval_manager = AsyncMock()
    messages = []

    approval_manager.wait_for_approval.return_value = ToolApprovalWaitResult(
        decisions=[
            ToolApprovalDecision(
                tool_call_id="call_1", approved=False, reason="timeout"
            )
        ],
        timed_out=True,
    )
    follow_up_stream = _AsyncChunkStream([_text_chunk("done", finish_reason="stop")])
    mocked_acompletion = AsyncMock(return_value=follow_up_stream)

    stream = _AsyncChunkStream(
        [_tool_call_chunk()],
        eneo_context={
            "mcp_proxy": mcp_proxy,
            "messages": messages,
            "kwargs": {},
            "has_tools": True,
        },
    )

    with patch(
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        mocked_acompletion,
    ):
        completions = await _collect(
            adapter,
            stream,
            require_tool_approval=True,
            approval_manager=approval_manager,
            approval_context={
                "tenant_id": uuid4(),
                "user_id": uuid4(),
                "session_id": uuid4(),
                "assistant_id": uuid4(),
            },
            pending_approval_ids=set(),
        )

    timeout_events = [
        c for c in completions if c.response_type == ResponseType.TOOL_APPROVAL_TIMEOUT
    ]
    assert len(timeout_events) == 1
    assert timeout_events[0].approval_id is not None

    denied_tool_messages = [m for m in messages if m.get("role") == "tool"]
    assert denied_tool_messages
    denied_payload = json.loads(denied_tool_messages[0]["content"])
    assert denied_payload["denied"] is True
    assert denied_payload["user_reason"] == "timeout"


@pytest.mark.asyncio
async def test_iterate_stream_denied_tools_produce_structured_denial_payload():
    adapter = _make_adapter()
    mcp_proxy = _FakeMCPProxy()
    approval_manager = AsyncMock()
    messages = []

    approval_manager.wait_for_approval.return_value = ToolApprovalWaitResult(
        decisions=[
            ToolApprovalDecision(
                tool_call_id="call_1",
                approved=False,
                reason="Need manual verification",
            )
        ],
        timed_out=False,
    )
    follow_up_stream = _AsyncChunkStream([_text_chunk("done", finish_reason="stop")])
    mocked_acompletion = AsyncMock(return_value=follow_up_stream)

    stream = _AsyncChunkStream(
        [_tool_call_chunk()],
        eneo_context={
            "mcp_proxy": mcp_proxy,
            "messages": messages,
            "kwargs": {},
            "has_tools": True,
        },
    )

    with patch(
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        mocked_acompletion,
    ):
        await _collect(
            adapter,
            stream,
            require_tool_approval=True,
            approval_manager=approval_manager,
            approval_context={
                "tenant_id": uuid4(),
                "user_id": uuid4(),
                "session_id": uuid4(),
                "assistant_id": uuid4(),
            },
            pending_approval_ids=set(),
        )

    denied_tool_messages = [m for m in messages if m.get("role") == "tool"]
    assert denied_tool_messages
    denied_payload = json.loads(denied_tool_messages[0]["content"])
    assert denied_payload == {
        "denied": True,
        "user_reason": "Need manual verification",
    }


@pytest.mark.asyncio
async def test_iterate_stream_approved_tools_execute_and_continue():
    adapter = _make_adapter()
    mcp_proxy = _FakeMCPProxy()
    approval_manager = AsyncMock()
    messages = []

    approval_manager.wait_for_approval.return_value = ToolApprovalWaitResult(
        decisions=[ToolApprovalDecision(tool_call_id="call_1", approved=True)],
        timed_out=False,
    )
    follow_up_stream = _AsyncChunkStream([_text_chunk("final", finish_reason="stop")])
    mocked_acompletion = AsyncMock(return_value=follow_up_stream)

    stream = _AsyncChunkStream(
        [_tool_call_chunk(arguments='{"q":"run"}')],
        eneo_context={
            "mcp_proxy": mcp_proxy,
            "messages": messages,
            "kwargs": {},
            "has_tools": True,
        },
    )

    with patch(
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        mocked_acompletion,
    ):
        completions = await _collect(
            adapter,
            stream,
            require_tool_approval=True,
            approval_manager=approval_manager,
            approval_context={
                "tenant_id": uuid4(),
                "user_id": uuid4(),
                "session_id": uuid4(),
                "assistant_id": uuid4(),
            },
            pending_approval_ids=set(),
        )

    assert mcp_proxy.calls == [[("server__tool", {"q": "run"})]]
    execution_events = [
        c
        for c in completions
        if c.response_type == ResponseType.TOOL_CALL
        and c.tool_calls_metadata
        and c.tool_calls_metadata[0].result_status == "succeeded"
    ]
    assert execution_events
