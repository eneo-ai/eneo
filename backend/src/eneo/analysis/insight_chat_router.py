"""Endpoints of the insights analysis chat.

Mounted under ``/analysis/conversation-insights/chat``. The wire format is
the regular conversation one (``AskChatResponse`` or the ``first_chunk`` /
``text`` / ``reasoning`` / ``tool_call`` / ``token_usage`` / ``error`` SSE
events) so the web app renders insight turns with its existing chat pieces.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Annotated

from fastapi import APIRouter, Depends
from sse_starlette import EventSourceResponse, ServerSentEvent

from eneo.ai_models.completion_models.completion_model import ResponseType
from eneo.analysis.insight_chat_models import InsightChatStartRequest
from eneo.analysis.insight_conversation_service import InsightTurn
from eneo.assistants.api.assistant_protocol import (
    to_ask_conversation_response,
    to_sse_response,
)
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import require_user_for_creation
from eneo.authentication.auth_models import audit_actor_for
from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.questions.question import UseTools
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.sessions.session import AskChatResponse, SSEFirstChunk

logger = get_logger(__name__)

router = APIRouter()


def to_turn_response(
    turn: InsightTurn, *, stream: bool, show_pricing: bool
) -> EventSourceResponse | AskChatResponse:
    """Render a turn as the conversation wire format."""
    no_tools = UseTools(assistants=[])
    if stream:

        async def event_stream():
            first = SSEFirstChunk(
                **to_ask_conversation_response(
                    question=turn.question,
                    files=[],
                    session=turn.session,
                    answer="",
                    info_blobs=[],
                    tools=no_tools,
                    completion_model=turn.completion_model,
                    show_pricing=show_pricing,
                    question_id=turn.question_id,
                    created_at=turn.created_at,
                ).model_dump()
            )
            yield ServerSentEvent(
                first.model_dump_json(), event=ResponseType.FIRST_CHUNK.value
            )
            assert not isinstance(turn.answer, str)
            async for chunk in turn.answer:
                yield to_sse_response(chunk=chunk, session_id=turn.session.id)

        return EventSourceResponse(event_stream(), ping=15)

    assert isinstance(turn.answer, str)
    return to_ask_conversation_response(
        question=turn.question,
        files=[],
        session=turn.session,
        answer=turn.answer,
        info_blobs=[],
        tools=no_tools,
        completion_model=turn.completion_model,
        show_pricing=show_pricing,
        question_id=turn.question_id,
        created_at=turn.created_at,
    )


@router.post(
    "/",
    response_model=AskChatResponse,
    description=(
        "Start an insights analysis conversation about an assistant or group "
        "chat. Streams Server-Sent Events when stream is true."
    ),
    responses=responses.streaming_response(AskChatResponse, [400, 403, 404]),
)
async def start_insight_conversation(
    body: InsightChatStartRequest,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _user_for_creation: None = Depends(require_user_for_creation),
):
    user = container.user()
    service = container.insight_conversation_service()
    selected_range = (
        (body.selected_range.start, body.selected_range.end)
        if body.selected_range is not None
        else None
    )
    turn = await service.start(
        assistant_id=body.assistant_id,
        group_chat_id=body.group_chat_id,
        question=body.question,
        timezone=body.timezone,
        stream=body.stream,
        selected_range=selected_range,
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
            f"Started insights conversation about {entity_type.value} "
            f"'{turn.target_name}'"
        ),
        metadata=AuditMetadata.standard(
            actor=user,
            target=SimpleNamespace(
                id=entity_id, name=turn.target_name, space_id=turn.space_id
            ),
            extra={
                "session_id": str(turn.session.id),
                "stream": body.stream,
                "timezone": body.timezone,
                "completion_model_id": str(turn.completion_model.id),
            },
        ),
    )

    return to_turn_response(
        turn, stream=body.stream, show_pricing=user.can_view_model_pricing
    )
