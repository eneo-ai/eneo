from __future__ import annotations

from typing import TYPE_CHECKING, Any

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    PersistedAssistantToolCall,
    RuntimeToolCall,
    persisted_assistant_tool_call_from_runtime,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendTurn

if TYPE_CHECKING:
    from eneo.flows.domain.flow import Flow


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
