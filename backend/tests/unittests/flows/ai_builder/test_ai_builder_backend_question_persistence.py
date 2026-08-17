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
from eneo.flows.ai_builder.planning_state import PlanningState


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
        "question_index": 3,
    }


def _expected_confirming_question_arguments() -> dict[str, object]:
    return {
        "question_id": "report_disposition",
        "question": "Hur ska rapporten sammanställas?",
        "options": [
            {
                "id": "confirm_combined_report",
                "value": "combined",
                "label": "En gemensam rapport",
                "description": "Sammanställ alla källor i en rapport.",
            }
        ],
        "selection_mode": "single",
        "allow_custom": False,
        "requires_confirm": True,
        "question_index": 1,
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
            "question_index": 1,
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
        planning_state=PlanningState.empty(),
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
        planning_state=PlanningState.empty(),
        question=BackendQuestion(
            question_data=StructuredQuestionPayload.model_validate(expected_arguments),
            assistant_text="Hur ska rapporten sammanställas?",
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
        planning_state=PlanningState.empty(),
        question=_backend_question(),
        assistant_metadata={
            "planner_telemetry": {
                "request_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            }
        },
    )

    assistant_msg = conversation[1]
    assert assistant_msg.metadata is not None
    assert assistant_msg.metadata["planner_telemetry"] == {
        "request_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
    assert assistant_msg.metadata["question_id"] == "runtime_metadata_fields"


@pytest.mark.asyncio
async def test_persist_backend_question_records_the_number_the_user_is_shown() -> None:
    # The number the user reads has to outlive the message order it was
    # computed from, so it is written down with the question rather than
    # recounted later.
    repo = AsyncMock()
    repo.commit_turn.return_value = 1
    conversation = [ConversationMessage(role="user", content="Bygg")]

    await persist_backend_question(
        repo=repo,
        turn=_make_turn(),
        conversation=conversation,
        new_messages_start=1,
        planning_state=PlanningState.empty(),
        question=_backend_question(),
    )

    assistant_msg = conversation[1]
    assert assistant_msg.metadata is not None
    assert assistant_msg.metadata["question_index"] == 3
    assert assistant_msg.tool_calls is not None
    assert assistant_msg.tool_calls[0]["arguments"]["question_index"] == 3


@pytest.mark.asyncio
async def test_persist_backend_question_refuses_an_unnumbered_question() -> None:
    # A question that reached persistence without a number means the writer
    # that numbers questions stopped doing so. Persisting it would bring back
    # the order-derived number this contract exists to remove.
    repo = AsyncMock()
    repo.commit_turn.return_value = 1

    with pytest.raises(ValueError, match="number it is shown with"):
        await persist_backend_question(
            repo=repo,
            turn=_make_turn(),
            conversation=[ConversationMessage(role="user", content="Bygg")],
            new_messages_start=1,
            planning_state=PlanningState.empty(),
            question=BackendQuestion(
                question_data=_backend_question().question_data.model_copy(
                    update={"question_index": None}
                ),
                assistant_text="Vilka fält behöver vi?",
            ),
        )


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
        planning_state=PlanningState.empty(),
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
        planning_state=PlanningState.empty(),
        question=_backend_question(),
        tool_content="Backend question presented after a repair attempt.",
    )

    tool_msg = conversation[2]
    assert tool_msg.role == "tool"
    assert tool_msg.content == "Backend question presented after a repair attempt."
