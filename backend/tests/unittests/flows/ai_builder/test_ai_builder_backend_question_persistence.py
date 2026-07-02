from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_backend_question_persistence import (
    persist_backend_question,
)
from eneo.flows.ai_builder.ai_builder_discovery_models import BackendQuestion
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_event_models import StructuredQuestionPayload
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)


def _make_turn() -> SessionSendTurn:
    return SessionSendTurn(
        session_id=uuid4(),
        tenant_id=uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=5,
    )


def _backend_question() -> BackendQuestion:
    return BackendQuestion(
        question_data=StructuredQuestionPayload.model_validate(
            _expected_question_arguments()
        ),
        assistant_text="Vilka fält behöver vi?",
    )


def _expected_question_arguments() -> dict[str, object]:
    return {
        "question_id": "runtime_metadata_fields",
        "question": "Vilka fält behöver vi?",
        "options": [
            {"value": "title", "label": "Rubrik", "description": None},
            {"value": "author", "label": "Författare", "description": None},
        ],
        "selection_mode": "multi",
        "allow_custom": False,
    }


def _expected_confirming_question_arguments() -> dict[str, object]:
    return {
        "question_id": "mcp_resource_selection",
        "question": "Ska AI Builder använda MCP-verktyg?",
        "options": [
            {
                "id": "continue_without_mcp",
                "value": "without_mcp",
                "label": "Fortsätt utan MCP",
                "description": "Bygg flödet utan externa MCP-verktyg.",
            }
        ],
        "selection_mode": "single",
        "allow_custom": False,
        "requires_confirm": True,
    }


def _empty_question_id_payload() -> StructuredQuestionPayload:
    return StructuredQuestionPayload.model_validate(
        {
            "question_id": "runtime_metadata_fields",
            "question": "Vad behöver du veta?",
            "options": [
                {
                    "value": "details",
                    "label": "Detaljer",
                    "description": None,
                }
            ],
            "selection_mode": "single",
            "allow_custom": True,
        }
    )


@pytest.mark.asyncio
async def test_persist_backend_question_commits_turn_with_flow_and_lease() -> None:
    repo = AsyncMock()
    repo.commit_turn.return_value = 23
    conversation = [
        ConversationMessage(role="user", content="Jag vill bygga en sammanställning")
    ]
    turn = _make_turn()
    flow = SimpleNamespace(id=uuid4())

    result = await persist_backend_question(
        repo=repo,
        turn=turn,
        conversation=conversation,
        new_messages_start=1,
        question=_backend_question(),
        flow=flow,  # type: ignore[arg-type]
    )

    assert len(conversation) == 3
    assistant_msg = conversation[1]
    tool_msg = conversation[2]
    assert assistant_msg.role == "assistant"
    assert assistant_msg.content == "Vilka fält behöver vi?"
    assert assistant_msg.tool_calls is not None
    assert assistant_msg.tool_calls[0]["name"] == "ask_structured_question"
    assert assistant_msg.tool_calls[0]["arguments"] == _expected_question_arguments()
    assert tool_msg.role == "tool"
    assert tool_msg.tool_call_id == assistant_msg.tool_calls[0]["id"]
    repo.commit_turn.assert_awaited_once()
    kwargs = repo.commit_turn.await_args.kwargs
    assert kwargs["turn"] == turn
    assert kwargs["flow"] is flow
    new_messages = kwargs["new_messages"]
    assert [message.role for message in new_messages] == ["assistant", "tool"]
    assert len(result.events) == 2
    assert result.new_planning_state_version == 23


@pytest.mark.asyncio
async def test_persist_backend_question_preserves_explicit_id_and_confirm_flag() -> (
    None
):
    repo = AsyncMock()
    repo.commit_turn.return_value = 1
    conversation = [ConversationMessage(role="user", content="Bygg")]
    expected_arguments = _expected_confirming_question_arguments()

    await persist_backend_question(
        repo=repo,
        turn=_make_turn(),
        conversation=conversation,
        new_messages_start=1,
        question=BackendQuestion(
            question_data=StructuredQuestionPayload.model_validate(expected_arguments),
            assistant_text="Ska AI Builder använda MCP-verktyg?",
        ),
    )

    assistant_msg = conversation[1]
    assert assistant_msg.tool_calls is not None
    assert assistant_msg.tool_calls[0]["arguments"] == expected_arguments


@pytest.mark.asyncio
async def test_persist_backend_question_merges_assistant_and_question_metadata() -> (
    None
):
    repo = AsyncMock()
    conversation = [ConversationMessage(role="user", content="Bygg")]

    await persist_backend_question(
        repo=repo,
        turn=_make_turn(),
        conversation=conversation,
        new_messages_start=1,
        question=_backend_question(),
        assistant_metadata={"planner_telemetry": {"request_id": "req-1"}},
    )

    assistant_msg = conversation[1]
    assert assistant_msg.metadata is not None
    assert assistant_msg.metadata["planner_telemetry"] == {"request_id": "req-1"}
    assert assistant_msg.metadata["question_id"] == "runtime_metadata_fields"


@pytest.mark.asyncio
async def test_persist_backend_question_omits_empty_metadata() -> None:
    repo = AsyncMock()
    repo.commit_turn.return_value = 1
    conversation = [ConversationMessage(role="user", content="Bygg")]

    await persist_backend_question(
        repo=repo,
        turn=_make_turn(),
        conversation=conversation,
        new_messages_start=1,
        question=BackendQuestion(
            question_data=_empty_question_id_payload().model_copy(
                update={"question_id": ""}
            ),
            assistant_text="Vad behöver du veta?",
        ),
    )

    assert conversation[1].metadata is None


@pytest.mark.asyncio
async def test_persist_backend_question_preserves_custom_tool_content() -> None:
    repo = AsyncMock()
    conversation = [ConversationMessage(role="user", content="Bygg")]

    await persist_backend_question(
        repo=repo,
        turn=_make_turn(),
        conversation=conversation,
        new_messages_start=1,
        question=_backend_question(),
        tool_content="Backend question presented after a repair attempt.",
    )

    tool_msg = conversation[2]
    assert tool_msg.role == "tool"
    assert tool_msg.content == "Backend question presented after a repair attempt."
