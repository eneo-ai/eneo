from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    make_persisted_assistant_tool_call,
    metadata_for_assistant_question,
)
from intric.flows.ai_builder.ai_builder_discovery_models import (
    BackendQuestion,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from intric.flows.ai_builder.ai_builder_events import (
    build_question_event,
    build_text_event,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from intric.flows.ai_builder.ai_builder_tools import ASK_STRUCTURED_QUESTION_TOOL_NAME
from intric.flows.domain.flow import Flow


@dataclass(frozen=True, slots=True)
class BackendQuestionPersistenceResult:
    events: list[dict[str, str]]
    new_planning_state_version: int


async def persist_backend_question(
    *,
    repo: AIBuilderRepository,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    question: BackendQuestion,
    assistant_metadata: dict[str, Any] | None = None,
    tool_content: str = "Question presented to user. Awaiting their selection.",
    flow: Flow | None = None,
) -> BackendQuestionPersistenceResult:
    """Append a backend-owned discovery question turn and refresh `PlanningState` atomically.

    Routes through `repo.commit_turn` so the conversation append and the
    planning-state save land in one savepoint. Answer metadata on the
    follow-up response changes derived slots, so skipping the refresh
    would leave the persisted state stale relative to the persisted
    conversation.
    """
    tool_call_id = f"discovery_{uuid4().hex[:12]}"
    question_metadata = metadata_for_assistant_question(question.question_data)
    metadata = {
        **(assistant_metadata or {}),
        **(question_metadata or {}),
    } or None
    tool_call = make_persisted_assistant_tool_call(
        tool_call_id=tool_call_id,
        tool_name=ASK_STRUCTURED_QUESTION_TOOL_NAME,
        arguments=question.question_data,
    )

    conversation.append(
        ConversationMessage(
            role="assistant",
            content=question.assistant_text,
            metadata=metadata,
            tool_calls=[tool_call.model_dump(mode="json")],
        )
    )
    conversation.append(
        ConversationMessage(
            role="tool",
            content=tool_content,
            tool_call_id=tool_call_id,
        )
    )

    new_version = await repo.commit_turn(
        turn=turn,
        new_messages=conversation[new_messages_start:],
        flow=flow,
    )

    return BackendQuestionPersistenceResult(
        events=[
            build_text_event(question.assistant_text),
            build_question_event(question.question_data),
        ],
        new_planning_state_version=new_version,
    )
