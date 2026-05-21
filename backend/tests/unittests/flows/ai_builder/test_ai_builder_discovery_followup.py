from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_discovery_followup import (
    persist_backend_question,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage


@pytest.mark.asyncio
async def test_persist_backend_question_commits_turn_with_flow_and_lease() -> None:
    repo = AsyncMock()
    conversation = [
        ConversationMessage(role="user", content="Jag vill bygga en sammanställning")
    ]
    session_id = uuid4()
    tenant_id = uuid4()
    request_id = uuid4()
    lock_token = uuid4()
    flow = SimpleNamespace(id=uuid4())

    events = await persist_backend_question(
        repo=repo,
        tenant_id=tenant_id,
        session_id=session_id,
        conversation=conversation,
        new_messages_start=1,
        base_planning_state_version=5,
        question_data={
            "question_id": "runtime_metadata_fields",
            "question": "Vilka fält behöver vi?",
            "options": [
                {"value": "title", "label": "Rubrik", "description": None},
                {"value": "author", "label": "Författare", "description": None},
            ],
            "selection_mode": "multi",
            "allow_custom": False,
        },
        assistant_text="Vilka fält behöver vi?",
        flow=flow,  # type: ignore[arg-type]
        lease_request_id=request_id,
        lease_lock_token=lock_token,
    )

    assert len(conversation) == 3
    assistant_msg = conversation[1]
    tool_msg = conversation[2]
    assert assistant_msg.role == "assistant"
    assert assistant_msg.content == "Vilka fält behöver vi?"
    assert assistant_msg.tool_calls is not None
    assert assistant_msg.tool_calls[0]["name"] == "ask_structured_question"
    assert tool_msg.role == "tool"
    assert tool_msg.tool_call_id == assistant_msg.tool_calls[0]["id"]
    repo.commit_turn.assert_awaited_once()
    kwargs = repo.commit_turn.await_args.kwargs
    assert kwargs["session_id"] == session_id
    assert kwargs["tenant_id"] == tenant_id
    assert kwargs["flow"] is flow
    assert kwargs["request_id"] == request_id
    assert kwargs["lock_token"] == lock_token
    assert kwargs["base_version"] == 5
    new_messages = kwargs["new_messages"]
    assert [message.role for message in new_messages] == ["assistant", "tool"]
    assert len(events) == 2
