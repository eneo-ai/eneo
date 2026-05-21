from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    append_retry_feedback_turn,
)
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    build_tool_retry_messages as build_proposal_tool_retry_messages,
)

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
    repo: Any,
    tenant_id: UUID,
    session_id: UUID,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    base_planning_state_version: int,
    tool_call: Any,
    arguments: dict[str, Any],
    tool_content: str,
    metadata: dict[str, Any] | None = None,
    assistant_content: str | None = None,
    assistant_metadata: dict[str, Any] | None = None,
    flow: "Flow | None" = None,
    lease_request_id: UUID | None = None,
    lease_lock_token: UUID | None = None,
) -> None:
    """Append an assistant tool call + tool response turn and refresh `PlanningState` atomically.

    Routes through `repo.commit_turn` so the conversation append and the
    planning-state save land in one savepoint. Tool metadata such as
    `requirements_summary` feeds signal extraction, so skipping the
    planning-state refresh would leave the persisted state stale relative
    to the persisted conversation.
    """
    conversation.append(
        ConversationMessage(
            role="assistant",
            content=assistant_content,
            metadata=assistant_metadata,
            tool_calls=[
                {
                    "id": tool_call.id,
                    "name": tool_call.function.name,
                    "arguments": arguments,
                }
            ],
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
    await repo.commit_turn(
        session_id=session_id,
        tenant_id=tenant_id,
        new_messages=conversation[new_messages_start:],
        flow=flow,
        request_id=lease_request_id,
        lock_token=lease_lock_token,
        base_version=base_planning_state_version,
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
