from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from intric.ai_models.completion_models.completion_model import ResponseType
from intric.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)
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


def _text_chunk(text: str, finish_reason: str | None = None):
    delta = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


class _FakeMCPProxy:
    def __init__(self):
        self.calls = []

    def get_allowed_tool_names(self):
        return {"server__tool"}

    def get_tool_info(self, prefixed_tool_name: str):
        return ("Server", "tool")

    async def call_tools_parallel(self, proxy_calls):
        self.calls.append(proxy_calls)
        return [{"content": [{"type": "text", "text": "tool-ok"}], "is_error": False}]


def _make_adapter() -> TenantModelAdapter:
    adapter = object.__new__(TenantModelAdapter)
    adapter.litellm_model = "openai/test-model"
    adapter.model = SimpleNamespace(name="test-model")
    return adapter


async def _collect(adapter: TenantModelAdapter, stream, **kwargs):
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
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter.litellm.acompletion",
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
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter.litellm.acompletion",
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

    assert any(c.response_type == ResponseType.TOOL_APPROVAL_REQUIRED for c in completions)
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
            ToolApprovalDecision(tool_call_id="call_1", approved=False, reason="timeout")
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
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter.litellm.acompletion",
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
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter.litellm.acompletion",
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
        "intric.completion_models.infrastructure.adapters.tenant_model_adapter.litellm.acompletion",
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
