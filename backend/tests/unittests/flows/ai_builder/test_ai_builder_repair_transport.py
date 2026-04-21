from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_create_tool_schema import CREATE_FLOW_TOOL_NAME
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
            name=CREATE_FLOW_TOOL_NAME,
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
    assert messages[1]["tool_calls"][0]["function"]["name"] == CREATE_FLOW_TOOL_NAME
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
async def test_persist_tool_turn_appends_messages_and_persists_new_slice() -> None:
    repo = AsyncMock()
    conversation = [ConversationMessage(role="user", content="Build a document flow")]
    tool_call = SimpleNamespace(
        id="call_2",
        function=SimpleNamespace(name="confirm_requirements"),
    )

    await persist_tool_turn(
        repo=repo,
        tenant_id=uuid4(),
        session_id=uuid4(),
        conversation=conversation,
        new_messages_start=1,
        tool_call=tool_call,
        arguments={"summary": "Kort sammanfattning"},
        tool_content="saved",
        assistant_content="Här är sammanfattningen.",
        metadata={"requirements_version": "req-v1"},
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
    repo.append_session_messages.assert_awaited_once()
