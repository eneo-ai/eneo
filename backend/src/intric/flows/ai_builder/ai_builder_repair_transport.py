from __future__ import annotations

from typing import TYPE_CHECKING, Any

from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    PersistedAssistantToolCall,
    RuntimeToolCall,
    persisted_assistant_tool_call_from_runtime,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    append_retry_feedback_turn,
)
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    build_tool_retry_messages as build_proposal_tool_retry_messages,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendTurn

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow


def build_tool_retry_messages(
    *,
    llm_messages: list[dict[str, Any]],
    tool_call: Any,
    tool_feedback: str,
    assistant_content: str | None = None,
) -> list[dict[str, Any]]:
    return build_proposal_tool_retry_messages(
        llm_messages=llm_messages,
        tool_call=tool_call,
        tool_feedback=tool_feedback,
        assistant_content=assistant_content,
    )


def append_tool_retry_feedback_turn(
    *,
    llm_messages: list[dict[str, Any]],
    tool_call: Any,
    assistant_content: str | None,
    tool_feedback: str,
) -> list[dict[str, Any]]:
    return append_retry_feedback_turn(
        llm_messages=llm_messages,
        tool_call=tool_call,
        assistant_content=assistant_content,
        tool_feedback=tool_feedback,
    )


async def persist_tool_turn(
    *,
    repo: AIBuilderRepository,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    tool_call: RuntimeToolCall | PersistedAssistantToolCall,
    arguments: dict[str, Any],
    tool_content: str,
    metadata: dict[str, Any] | None = None,
    assistant_content: str | None = None,
    assistant_metadata: dict[str, Any] | None = None,
    flow: "Flow | None" = None,
) -> int:
    """Append an assistant tool call + tool response turn and refresh `PlanningState` atomically.

    Routes through `repo.commit_turn` so the conversation append and the
    planning-state save land in one savepoint. Tool metadata such as
    `requirements_summary` feeds signal extraction, so skipping the
    planning-state refresh would leave the persisted state stale relative
    to the persisted conversation.
    """
    persisted_tool_call = persisted_assistant_tool_call_from_runtime(
        tool_call,
        arguments=arguments,
    )
    conversation.append(
        ConversationMessage(
            role="assistant",
            content=assistant_content,
            metadata=assistant_metadata,
            tool_calls=[
                persisted_tool_call.model_dump(mode="json"),
            ],
        )
    )
    conversation.append(
        ConversationMessage(
            role="tool",
            content=tool_content,
            tool_call_id=persisted_tool_call.id,
            metadata=metadata,
        )
    )
    return await repo.commit_turn(
        turn=turn,
        new_messages=conversation[new_messages_start:],
        flow=flow,
    )
