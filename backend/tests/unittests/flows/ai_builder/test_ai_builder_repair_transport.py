from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_create_outline import OUTLINE_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_repair_transport import (
    build_persisted_tool_call_stub,
    build_tool_retry_messages,
    persist_tool_turn,
)


def test_build_tool_retry_messages_appends_tool_call_and_feedback() -> None:
    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(
            name=OUTLINE_FLOW_TOOL_NAME,
            arguments='{"flow_name":"Draft"}',
        ),
    )

    messages = build_tool_retry_messages(
        llm_messages=[{"role": "system", "content": "Prompt"}],
        tool_call=tool_call,
        tool_feedback="Please fix the draft.",
    )

    assert messages[0] == {"role": "system", "content": "Prompt"}
    assert messages[1]["role"] == "assistant"
    assert messages[1]["tool_calls"][0]["function"]["name"] == OUTLINE_FLOW_TOOL_NAME
    assert messages[2] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "Please fix the draft.",
    }


def test_build_persisted_tool_call_stub_returns_minimal_tool_shape() -> None:
    stub = build_persisted_tool_call_stub(
        tool_call_id="call_2",
        tool_name="confirm_requirements",
    )

    assert stub.id == "call_2"
    assert stub.function.name == "confirm_requirements"


@pytest.mark.asyncio
async def test_persist_tool_turn_commits_turn_with_flow_and_lease() -> None:
    repo = AsyncMock()
    conversation = [ConversationMessage(role="user", content="Build a document flow")]
    tool_call = SimpleNamespace(
        id="call_2",
        function=SimpleNamespace(name="confirm_requirements"),
    )
    session_id = uuid4()
    tenant_id = uuid4()
    request_id = uuid4()
    lock_token = uuid4()
    flow = SimpleNamespace(id=uuid4())

    await persist_tool_turn(
        repo=repo,
        tenant_id=tenant_id,
        session_id=session_id,
        conversation=conversation,
        new_messages_start=1,
        base_planning_state_version=6,
        tool_call=tool_call,
        arguments={"summary": "Kort sammanfattning"},
        tool_content="saved",
        assistant_content="Här är sammanfattningen.",
        metadata={"requirements_version": "req-v1"},
        flow=flow,  # type: ignore[arg-type]
        lease_request_id=request_id,
        lease_lock_token=lock_token,
    )

    assert len(conversation) == 3
    assert conversation[1].role == "assistant"
    assert conversation[1].tool_calls == [
        {
            "id": "call_2",
            "name": "confirm_requirements",
            "arguments": {"summary": "Kort sammanfattning"},
        }
    ]
    tool_message = conversation[2]
    assert tool_message.role == "tool"
    assert tool_message.content == "saved"
    assert tool_message.tool_call_id == "call_2"
    assert tool_message.metadata == {"requirements_version": "req-v1"}
    repo.commit_turn.assert_awaited_once()
    kwargs = repo.commit_turn.await_args.kwargs
    assert kwargs["session_id"] == session_id
    assert kwargs["tenant_id"] == tenant_id
    assert kwargs["flow"] is flow
    assert kwargs["request_id"] == request_id
    assert kwargs["lock_token"] == lock_token
    assert kwargs["base_version"] == 6
    new_messages = kwargs["new_messages"]
    assert [message.role for message in new_messages] == ["assistant", "tool"]
    assert new_messages[1].metadata == {"requirements_version": "req-v1"}
