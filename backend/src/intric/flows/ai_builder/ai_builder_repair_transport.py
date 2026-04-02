from __future__ import annotations

from typing import Any
from uuid import UUID

from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_plan_store import append_session_messages
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    append_retry_feedback_turn,
    build_tool_retry_messages as build_proposal_tool_retry_messages,
)


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
    repo: Any,
    tenant_id: UUID,
    session_id: UUID,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    tool_call: Any,
    arguments: dict[str, Any],
    tool_content: str,
    metadata: dict[str, Any] | None = None,
    assistant_content: str | None = None,
) -> None:
    conversation.append(
        ConversationMessage(
            role="assistant",
            content=assistant_content,
            tool_calls=[{
                "id": tool_call.id,
                "name": tool_call.function.name,
                "arguments": arguments,
            }],
        )
    )
    conversation.append(
        ConversationMessage(
            role="tool",
            content=tool_content,
            tool_call_id=tool_call.id,
            metadata=metadata,
        )
    )
    await append_session_messages(
        repo=repo,
        tenant_id=tenant_id,
        session_id=session_id,
        conversation=conversation,
        start_index=new_messages_start,
    )


def build_persisted_tool_call_stub(*, tool_call_id: str, tool_name: str) -> Any:
    return type(
        "ToolCallStub",
        (),
        {
            "id": tool_call_id,
            "function": type(
                "FunctionStub",
                (),
                {"name": tool_name},
            )(),
        },
    )()
