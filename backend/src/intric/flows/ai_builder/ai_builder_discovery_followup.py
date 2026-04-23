from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from intric.flows.ai_builder.ai_builder_discovery_runtime import (
    build_discovery_followup_runtime,
)
from intric.flows.ai_builder.ai_builder_events import (
    build_question_event,
    build_text_event,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_tools import ASK_STRUCTURED_QUESTION_TOOL_NAME
from intric.flows.domain.flow import Flow


async def persist_backend_question(
    *,
    repo: AIBuilderRepository,
    tenant_id: UUID,
    session_id: UUID,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    question_data: dict[str, object],
    assistant_text: str,
    assistant_metadata: dict[str, Any] | None = None,
    tool_content: str = "Question presented to user. Awaiting their selection.",
    flow: Flow | None = None,
    lease_request_id: UUID | None = None,
    lease_lock_token: UUID | None = None,
) -> list[dict[str, str]]:
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

    await repo.commit_turn(
        session_id=session_id,
        tenant_id=tenant_id,
        new_messages=conversation[new_messages_start:],
        flow=flow,
        request_id=lease_request_id,
        lock_token=lease_lock_token,
    )

    return [
        build_text_event(assistant_text),
        build_question_event(question_data),
    ]


async def emit_discovery_followup_if_needed(
    *,
    repo: AIBuilderRepository,
    tenant_id: UUID,
    session_id: UUID,
    conversation: list[ConversationMessage],
    new_messages_start: int,
    flow: Flow | None = None,
    litellm_client: Any | None = None,
    litellm_model: str | None = None,
    litellm_kwargs: dict[str, Any] | None = None,
    ui_language: str | None = None,
    assistant_metadata: dict[str, Any] | None = None,
    lease_request_id: UUID | None = None,
    lease_lock_token: UUID | None = None,
) -> list[dict[str, str]]:
    """Persist and return the next backend-generated discovery follow-up, if any."""
    followup, _analysis = await build_discovery_followup_runtime(
        conversation,
        flow=flow,
        litellm_client=litellm_client,
        litellm_model=litellm_model,
        litellm_kwargs=litellm_kwargs,
        ui_language=ui_language,
    )
    if followup is None:
        return []

    _issue, question_data, assistant_text = followup
    return await persist_backend_question(
        repo=repo,
        tenant_id=tenant_id,
        session_id=session_id,
        conversation=conversation,
        new_messages_start=new_messages_start,
        question_data=question_data,
        assistant_text=assistant_text,
        flow=flow,
        assistant_metadata=assistant_metadata,
        lease_request_id=lease_request_id,
        lease_lock_token=lease_lock_token,
    )
