from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    make_persisted_assistant_tool_call,
    metadata_for_assistant_question,
)
from eneo.flows.ai_builder.ai_builder_discovery_models import (
    BackendQuestion,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    AIBuilderStreamEvent,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_events import (
    build_question_event,
    build_text_event,
)
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn
from eneo.flows.ai_builder.ai_builder_tool_names import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
)
from eneo.flows.domain.flow import Flow, FlowPersistedJsonObject


@dataclass(frozen=True, slots=True)
class BackendQuestionPersistenceResult:
    events: tuple[AIBuilderStreamEvent, ...]
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
        arguments=_persisted_question_arguments(question.question_data),
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
        events=(
            build_text_event(question.assistant_text),
            build_question_event(question.question_data),
        ),
        new_planning_state_version=new_version,
    )


def _persisted_question_arguments(
    question_data: StructuredQuestionPayload,
) -> FlowPersistedJsonObject:
    return question_data.model_dump(
        mode="json",
        exclude_none=False,
        exclude_unset=True,
    )
