from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from intric.flows.ai_builder.ai_builder_discovery_runtime import (
    build_discovery_followup_runtime,
)
from intric.flows.ai_builder.ai_builder_events import (
    build_question_event,
    build_text_event,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
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
    question_data: dict[str, object],
    assistant_text: str,
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

    conversation.append(
        ConversationMessage(
            role="assistant",
            content=assistant_text,
            metadata=assistant_metadata,
            tool_calls=[
                {
                    "id": tool_call_id,
                    "name": ASK_STRUCTURED_QUESTION_TOOL_NAME,
                    "arguments": question_data,
                }
            ],
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
            build_text_event(assistant_text),
            build_question_event(question_data),
        ],
        new_planning_state_version=new_version,
    )


async def emit_discovery_followup_if_needed(
    *,
    repo: AIBuilderRepository,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    flow: Flow | None = None,
    litellm_client: Any | None = None,
    litellm_model: str | None = None,
    litellm_kwargs: dict[str, Any] | None = None,
    ui_language: str | None = None,
    assistant_metadata: dict[str, Any] | None = None,
) -> BackendQuestionPersistenceResult | None:
    """Persist and return the next backend-generated discovery follow-up, if any."""
    followup, _analysis, _planning_state = await build_discovery_followup_runtime(
        conversation,
        flow=flow,
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        ui_language=ui_language,
        tenant_id=turn.tenant_id,
    )
    if followup is None:
        return None

    _issue, question_data, assistant_text = followup
    return await persist_backend_question(
        repo=repo,
        turn=turn,
        conversation=conversation,
        new_messages_start=new_messages_start,
        question_data=question_data,
        assistant_text=assistant_text,
        flow=flow,
        assistant_metadata=assistant_metadata,
    )
