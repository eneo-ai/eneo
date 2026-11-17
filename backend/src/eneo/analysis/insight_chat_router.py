"""Endpoints of the insights analysis chat.

Mounted under ``/analysis/conversation-insights/chat``. A turn streams the
chat API's version 3 UI Message Stream (``eneo.conversations.ui_message_stream``,
contract in ``frontend/apps/web-next/src/lib/chat/CONTRACT.md``), so the
web app renders an analysis with its chat view. A saved analysis reads back
as a ``SessionPublic`` and a tool call's result is read through its own
endpoint, as in the chat API.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sse_starlette import EventSourceResponse

from eneo.ai_models.completion_models.completion_model import CompletionModelPublic
from eneo.analysis.insight_chat_models import (
    InsightChatContinueRequest,
    InsightChatStartRequest,
    InsightSelectedRange,
)
from eneo.analysis.insight_conversation_service import InsightTurn
from eneo.assistants.api.assistant_models import AssistantResponse
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import require_user_for_creation
from eneo.authentication.auth_models import audit_actor_for
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.conversations.ui_message_stream import to_ui_message_stream_response
from eneo.database.database import AsyncSession
from eneo.main.container.container import Container
from eneo.main.models import CursorPaginatedResponse
from eneo.questions.question import UseTools
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.sessions.session import (
    SessionMetadataPublic,
    SessionPublic,
    ToolCallResultPublic,
)
from eneo.sessions.session_protocol import to_session_public

_TARGET_INSIGHTS_ACCESS_REASON = (
    "InsightConversationService checks insight access to the requested "
    "assistant or group chat."
)
_OWN_CONVERSATION_ACCESS_REASON = (
    "InsightConversationService admits only the caller's own insights "
    "conversation and checks insight access to its assistant or group chat."
)
_STREAM_DESCRIPTION = (
    "Streams the answer as the chat API's version 3 UI Message Stream "
    "(Server-Sent Events, header x-vercel-ai-ui-message-stream: v1)."
)

router = APIRouter()


def _range(selected: InsightSelectedRange | None):
    return (selected.start, selected.end) if selected is not None else None


def _stream(
    turn: InsightTurn, *, http_request: Request, show_pricing: bool
) -> EventSourceResponse:
    """The turn as the chat's version 3 stream, through the chat's encoder.

    An analysis has no attachments, no knowledge passages and no answering
    member assistant, so those parts of the stream stay empty; its tool calls
    are those of the loopback insights server.
    """
    response = AssistantResponse(
        session=turn.session,
        question=turn.question,
        question_id=turn.question_id,
        created_at=turn.created_at,
        files=[],
        answer=turn.answer,
        info_blobs=[],
        completion_model=CompletionModelPublic.from_domain(
            turn.completion_model, show_pricing=show_pricing
        ),
        tools=UseTools(assistants=[]),
    )
    return to_ui_message_stream_response(
        response=response, base_url=str(http_request.base_url)
    )


@router.post(
    "/",
    response_model=None,
    description=(
        "Start an insights analysis conversation about an assistant or group "
        f"chat. {_STREAM_DESCRIPTION}"
    ),
    responses=responses.streaming_response(response_codes=[400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_TARGET_INSIGHTS_ACCESS_REASON,
)
async def start_insight_conversation(
    body: InsightChatStartRequest,
    http_request: Request,
    container: Annotated[
        Container, Depends(get_container(with_user=True, with_transaction=False))
    ],
    _user_for_creation: Annotated[None, Depends(require_user_for_creation)],
) -> EventSourceResponse:
    user = container.user()
    session = cast(AsyncSession, container.session())
    # The setup commits before the answer streams: the stream writes the
    # answer in a transaction of its own, as the chat API's does.
    async with session.begin():
        turn = await container.insight_conversation_service().start(
            assistant_id=body.assistant_id,
            group_chat_id=body.group_chat_id,
            question=body.question,
            timezone=body.timezone,
            selected_range=_range(body.selected_range),
        )

    if body.assistant_id is not None:
        entity_type, entity_id = EntityType.ASSISTANT, body.assistant_id
    else:
        assert body.group_chat_id is not None
        entity_type, entity_id = EntityType.GROUP_CHAT, body.group_chat_id
    actor_id, actor_type = audit_actor_for(user)
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=actor_id,
        actor_type=actor_type,
        action=ActionType.INSIGHT_CONVERSATION_STARTED,
        entity_type=entity_type,
        entity_id=entity_id,
        description=(
            f"Started an insights conversation about {entity_type.value} "
            f"'{turn.target_name}'"
        ),
        metadata=AuditMetadata.standard(
            actor=user,
            target=SimpleNamespace(
                id=entity_id, name=turn.target_name, space_id=turn.space_id
            ),
            extra={
                "session_id": str(turn.session.id),
                "timezone": body.timezone,
                "completion_model_id": str(turn.completion_model.id),
            },
        ),
    )

    return _stream(
        turn, http_request=http_request, show_pricing=user.can_view_model_pricing
    )


@router.get(
    "/",
    response_model=CursorPaginatedResponse[SessionMetadataPublic],
    description=(
        "The caller's own insights conversations about an assistant or group "
        "chat, newest first. Each is named by the question it started with. "
        "One is no longer listed once a conversation it read was removed. "
        "Pass a page's next_cursor back as cursor for the next page."
    ),
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_TARGET_INSIGHTS_ACCESS_REASON,
)
async def list_insight_conversations(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    assistant_id: UUID | None = None,
    group_chat_id: UUID | None = None,
    limit: Annotated[int, Query(gt=0, le=100)] = 20,
    cursor: Annotated[
        str | None,
        Query(description="The next_cursor of the previous page, as given."),
    ] = None,
) -> CursorPaginatedResponse[SessionMetadataPublic]:
    page = await container.insight_conversation_service().list_conversations(
        assistant_id=assistant_id,
        group_chat_id=group_chat_id,
        limit=limit,
        cursor=cursor,
    )
    return CursorPaginatedResponse(
        items=page.items,
        total_count=page.total,
        limit=limit,
        previous_cursor=cursor,
        next_cursor=page.next_cursor,
    )


@router.get(
    "/{session_id}/",
    response_model=SessionPublic,
    description=(
        "One of the caller's insights conversations with all its turns. 410 "
        "(derived_source_removed) once a conversation it read was removed."
    ),
    responses=responses.get_responses([403, 404, 410]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_OWN_CONVERSATION_ACCESS_REASON,
)
async def get_insight_conversation(
    session_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> SessionPublic:
    session = await container.insight_conversation_service().get_conversation(
        session_id
    )
    return to_session_public(session)


@router.get(
    "/{session_id}/tool-calls/{tool_call_id}/result/",
    response_model=ToolCallResultPublic,
    description=(
        "Read one tool call's result from an insights conversation; the "
        "stream and the saved conversation carry its status only."
    ),
    responses=responses.get_responses([403, 404, 410]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_OWN_CONVERSATION_ACCESS_REASON,
)
async def get_insight_tool_call_result(
    session_id: UUID,
    tool_call_id: str,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> ToolCallResultPublic:
    tool_call = await container.insight_conversation_service().get_tool_call_result(
        session_id, tool_call_id
    )
    return ToolCallResultPublic(
        tool_call_id=tool_call_id,
        result=tool_call.result,
        mcp_tool_name=tool_call.mcp_tool_name,
        structured_content=tool_call.structured_content,
        is_error=tool_call.result_status == "failed",
    )


@router.post(
    "/{session_id}/",
    response_model=None,
    description=(
        "A follow-up question in one of the caller's insights conversations. "
        f"{_STREAM_DESCRIPTION}"
    ),
    responses=responses.streaming_response(response_codes=[400, 403, 404, 410]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_OWN_CONVERSATION_ACCESS_REASON,
)
async def continue_insight_conversation(
    session_id: UUID,
    body: InsightChatContinueRequest,
    http_request: Request,
    container: Annotated[
        Container, Depends(get_container(with_user=True, with_transaction=False))
    ],
    _user_for_creation: Annotated[None, Depends(require_user_for_creation)],
) -> EventSourceResponse:
    user = container.user()
    session = cast(AsyncSession, container.session())
    async with session.begin():
        turn = await container.insight_conversation_service().continue_turn(
            session_id=session_id,
            question=body.question,
            selected_range=_range(body.selected_range),
        )
    return _stream(
        turn, http_request=http_request, show_pricing=user.can_view_model_pricing
    )


@router.delete(
    "/{session_id}/",
    status_code=204,
    description="Delete one of the caller's insights conversations.",
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_OWN_CONVERSATION_ACCESS_REASON,
)
async def delete_insight_conversation(
    session_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> None:
    user = container.user()
    link = await container.insight_conversation_service().delete_conversation(
        session_id
    )
    if link.assistant_id is not None:
        entity_type, entity_id = EntityType.ASSISTANT, link.assistant_id
    else:
        entity_type, entity_id = EntityType.GROUP_CHAT, link.target_id
    actor_id, actor_type = audit_actor_for(user)
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=actor_id,
        actor_type=actor_type,
        action=ActionType.INSIGHT_CONVERSATION_DELETED,
        entity_type=entity_type,
        entity_id=entity_id,
        description=(
            f"Deleted an insights conversation about {entity_type.value} {entity_id}"
        ),
        metadata=AuditMetadata.standard(
            actor=user,
            target=SimpleNamespace(id=entity_id, name=None),
            extra={"session_id": str(session_id)},
        ),
    )
