from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from intric.assistants.api.assistant_protocol import to_conversation_response
from intric.conversations.conversation_models import ConversationRequest
from intric.database.database import AsyncSession, get_session_with_transaction
from intric.main.container.container import Container
from intric.main.config import get_settings
from intric.main.exceptions import NotFoundException
from intric.main.logging import get_logger
from intric.main.models import CursorPaginatedResponse
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.sessions.session import (
    SessionFeedback,
    SessionMetadataPublic,
    SessionPublic,
    SSEError,
    SSEFiles,
    SSEFirstChunk,
    SSEIntricEvent,
    SSEText,
)
from intric.sessions.session_protocol import (
    to_session_public,
    to_sessions_paginated_response,
)

logger = get_logger(__name__)

router = APIRouter()


async def _validate_conversation_scope(
    http_request: Request,
    container: Container,
    assistant_id: UUID | None,
    group_chat_id: UUID | None,
    session_id: UUID | None,
) -> None:
    """Validate body-driven fields against API key scope.

    Runs after auth (request.state has scope info) but before service call.
    Only validates when scope enforcement is active and key is non-tenant.
    Gated by the same env flag + tenant feature flag as _enforce_api_key_scope().
    """
    # Check env-level kill switch
    if not get_settings().api_key_enforce_scope:
        return

    scope_type = getattr(http_request.state, "api_key_scope_type", None)
    scope_id = getattr(http_request.state, "api_key_scope_id", None)
    if scope_type is None or scope_type == "tenant":
        return

    # Check tenant-level feature flag
    try:
        feature_flag_service = container.feature_flag_service()
        flag = await feature_flag_service.feature_flag_repo.one_or_none(
            name="api_key_scope_enforcement"
        )
        if flag is not None:
            user = container.user()
            if not flag.is_enabled(tenant_id=user.tenant_id):
                return
    except Exception:
        # Fail-closed: if we can't check the flag, enforce scope
        logger.warning("Could not check scope enforcement feature flag, defaulting to enforced")

    scope_id = UUID(str(scope_id)) if scope_id is not None else None

    # App-scoped keys cannot create conversations at all
    if scope_type == "app":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "insufficient_scope",
                "message": (
                    f"API key is scoped to app '{scope_id}'. "
                    f"It can only access that app and its runs."
                ),
            },
        )

    space_repo = container.space_repo()

    # If continuing an existing session, resolve it to validate scope
    if session_id is not None:
        session_service = container.session_service()
        try:
            session = await session_service.get_session_by_uuid(session_id)
        except NotFoundException:
            # Session doesn't exist — return 403 (not 404) to prevent
            # scoped keys from enumerating session existence.
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "insufficient_scope",
                    "message": "Unable to verify API key scope for this session.",
                },
            )
        except Exception:
            # DB error or unexpected failure — fail-closed: deny access
            logger.error(
                "Failed to resolve session for scope validation",
                extra={"session_id": str(session_id)},
                exc_info=True,
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "insufficient_scope",
                    "message": "Unable to verify API key scope for this session.",
                },
            )

        if scope_type == "assistant":
            session_assistant_id = session.assistant.id if session.assistant else None
            if session_assistant_id != scope_id:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "insufficient_scope",
                        "message": (
                            f"API key is scoped to assistant '{scope_id}'. "
                            f"It can only access that assistant and its conversations."
                        ),
                    },
                )
        elif scope_type == "space":
            # Resolve session to space via assistant or group_chat
            try:
                space = await space_repo.get_space_by_session(session_id)
                if space.id != scope_id:
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "code": "insufficient_scope",
                            "message": (
                                f"API key is scoped to space '{scope_id}'. "
                                f"The requested resource belongs to a different scope."
                            ),
                        },
                    )
            except NotFoundException:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "insufficient_scope",
                        "message": (
                            f"API key is scoped to space '{scope_id}'. "
                            f"The requested resource belongs to a different scope."
                        ),
                    },
                )
        return

    # New conversation with assistant_id
    if assistant_id is not None:
        if scope_type == "assistant":
            if assistant_id != scope_id:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "insufficient_scope",
                        "message": (
                            f"API key is scoped to assistant '{scope_id}'. "
                            f"It can only access that assistant and its conversations."
                        ),
                    },
                )
        elif scope_type == "space":
            try:
                space = await space_repo.get_space_by_assistant(assistant_id)
                if space.id != scope_id:
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "code": "insufficient_scope",
                            "message": (
                                f"API key is scoped to space '{scope_id}'. "
                                f"The requested resource belongs to a different scope."
                            ),
                        },
                    )
            except NotFoundException:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "insufficient_scope",
                        "message": (
                            f"API key is scoped to space '{scope_id}'. "
                            f"The requested resource belongs to a different scope."
                        ),
                    },
                )
        return

    # New conversation with group_chat_id
    if group_chat_id is not None:
        if scope_type == "assistant":
            # Assistant-scoped keys cannot access group chats
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "insufficient_scope",
                    "message": (
                        f"API key is scoped to assistant '{scope_id}'. "
                        f"It can only access that assistant and its conversations."
                    ),
                },
            )
        elif scope_type == "space":
            try:
                space = await space_repo.get_space_by_group_chat(group_chat_id)
                if space.id != scope_id:
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "code": "insufficient_scope",
                            "message": (
                                f"API key is scoped to space '{scope_id}'. "
                                f"The requested resource belongs to a different scope."
                            ),
                        },
                    )
            except NotFoundException:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "insufficient_scope",
                        "message": (
                            f"API key is scoped to space '{scope_id}'. "
                            f"The requested resource belongs to a different scope."
                        ),
                    },
                )


@router.post(
    "/",
    responses=responses.streaming_response(
        response_codes=[400, 404],
        models=[SSEText, SSEIntricEvent, SSEFiles, SSEFirstChunk, SSEError],
    ),
)
async def chat(
    request: ConversationRequest,
    http_request: Request,
    version: int = Query(default=1, ge=1, le=2),
    container: Container = Depends(get_container(with_user=True)),
    db_session: AsyncSession = Depends(get_session_with_transaction),
):
    """Unified endpoint for communicating with an assistant or a group chat.

    If request.session_id is provided: continues an existing conversation.
    Otherwise: starts a new conversation with the specified assistant or group chat.

    Either request.session_id, request.assistant_id, or request.group_chat_id must be provided.

    For group chats:
    - Specify the group_chat_id to chat with a group chat
    - If tools.assistants contains an assistant, that specific assistant will be targeted
      (requires the group chat to have allow_mentions=True).
    - If no assistant is targeted, the most appropriate assistant will be selected.
    - When multiple assistants could answer a question, the system will choose the most relevant one
      or select the first matching assistant if relevance scores are similar.

    For regular assistants:
    - The tools.assistants field can be used for directing the request to a tool assistant.

    Streams the response as Server-Sent Events if stream == true.
    The following SSE response models are supported in the stream:
    - SSEText: Text completion chunks
    - SSEIntricEvent: Internal events like generating an image
    - SSEFiles: Generated files/images responses
    - SSEFirstChunk: Initial response with metadata
    - SSEError: Error events (API errors, authentication failures, rate limits, etc.)
    """
    # Body-driven scope validation (before service call)
    await _validate_conversation_scope(
        http_request=http_request,
        container=container,
        assistant_id=request.assistant_id,
        group_chat_id=request.group_chat_id,
        session_id=request.session_id,
    )

    file_ids = [file.id for file in request.files]
    tool_assistant_id = None
    if request.tools is not None and request.tools.assistants:
        tool_assistant_id = request.tools.assistants[0].id

    # Use the dedicated ConversationService to handle routing logic
    conversation_service = container.conversation_service()
    response = await conversation_service.ask_conversation(
        question=request.question,
        session_id=request.session_id,
        assistant_id=request.assistant_id,
        group_chat_id=request.group_chat_id,
        file_ids=file_ids,
        stream=request.stream,
        tool_assistant_id=tool_assistant_id,
        version=version,
        use_web_search=request.use_web_search,
    )

    return await to_conversation_response(
        response=response, db_session=db_session, stream=request.stream
    )


@router.get(
    "/",
    response_model=CursorPaginatedResponse[SessionMetadataPublic],
    responses=responses.get_responses([400, 404]),
)
async def list_conversations(
    http_request: Request,
    assistant_id: Optional[UUID] = Query(None, description="The UUID of the assistant"),
    group_chat_id: Optional[UUID] = Query(None, description="The UUID of the group chat"),
    limit: int = Query(default=None, gt=0),
    cursor: datetime = None,
    previous: bool = False,
    container: Container = Depends(get_container(with_user=True)),
):
    """Gets conversations (sessions) for an assistant or group chat.

    Provide either assistant_id or group_chat_id (but not both) to filter sessions.
    If neither is provided, an error will be returned.
    """
    # Query-param scope validation (same rules as body-driven POST)
    await _validate_conversation_scope(
        http_request=http_request,
        container=container,
        assistant_id=assistant_id,
        group_chat_id=group_chat_id,
        session_id=None,
    )

    if assistant_id is None and group_chat_id is None:
        raise HTTPException(
            status_code=400,
            detail="Either assistant_id or group_chat_id must be provided",
        )
    if assistant_id is not None and group_chat_id is not None:
        raise HTTPException(
            status_code=400,
            detail="Provide either assistant_id or group_chat_id, not both",
        )

    session_service = container.session_service()

    if assistant_id is not None:
        # Get assistant service to validate the assistant exists and user has access
        assistant_service = container.assistant_service()
        await assistant_service.get_assistant(assistant_id)

        sessions, total_count = await session_service.get_sessions_by_assistant(
            assistant_id=assistant_id,
            limit=limit,
            cursor=cursor,
            previous=previous,
        )
    else:
        # Get group chat service to validate the group chat exists and user has access
        group_chat_service = container.group_chat_service()
        await group_chat_service.get_group_chat(group_chat_id=group_chat_id)

        sessions, total_count = await session_service.get_sessions_by_group_chat(
            group_chat_id=group_chat_id,
            limit=limit,
            cursor=cursor,
            previous=previous,
        )

    return to_sessions_paginated_response(
        sessions=sessions,
        limit=limit,
        cursor=cursor,
        previous=previous,
        total_count=total_count,
    )


@router.get(
    "/{session_id}/",
    response_model=SessionPublic,
    responses=responses.get_responses([400, 404]),
)
async def get_conversation(
    session_id: UUID = Path(..., description="The UUID of the conversation/session"),
    container: Container = Depends(get_container(with_user=True)),
):
    """Gets a specific conversation by its session ID"""
    session_service = container.session_service()
    session = await session_service.get_session_by_uuid(session_id)

    return to_session_public(session)


@router.delete(
    "/{session_id}/",
    status_code=204,
    responses=responses.get_responses([400, 404]),
)
async def delete_conversation(
    session_id: UUID = Path(..., description="The UUID of the conversation/session"),
    container: Container = Depends(get_container(with_user=True)),
):
    """Deletes a specific conversation"""
    session_service = container.session_service()
    # Note: We'll need to determine if this is an assistant or group chat session
    session = await session_service.get_session_by_uuid(session_id)

    if session.group_chat_id:
        await session_service.delete(session_id, group_chat_id=session.group_chat_id)
    else:
        await session_service.delete(session_id, assistant_id=session.assistant.id)

    # Return None to produce 204 No Content response
    return None


@router.post(
    "/{session_id}/feedback/",
    response_model=SessionPublic,
    responses=responses.get_responses([400, 404]),
)
async def leave_feedback(
    feedback: SessionFeedback,
    session_id: UUID = Path(..., description="The UUID of the conversation/session"),
    container: Container = Depends(get_container(with_user=True)),
):
    """Leave feedback for a conversation"""
    session_service = container.session_service()

    # Determine if this is a group chat or assistant session
    session = await session_service.get_session_by_uuid(session_id)

    if session.group_chat_id:
        updated_session = await session_service.leave_feedback(
            session_id=session_id,
            group_chat_id=session.group_chat_id,
            feedback=feedback,
        )
    else:
        updated_session = await session_service.leave_feedback(
            session_id=session_id, assistant_id=session.assistant.id, feedback=feedback
        )

    return to_session_public(updated_session)


@router.post(
    "/{session_id}/title/",
    response_model=SessionPublic,
    responses=responses.get_responses([400, 404]),
)
async def set_title_of_conversation(
    session_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    """Set the title of a conversation"""
    conversation_service = container.conversation_service()
    session = await conversation_service.set_title_of_conversation(session_id)
    return to_session_public(session)
