from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sse_starlette import EventSourceResponse, ServerSentEvent

from intric.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModel,
    ResponseType,
)
from intric.database.database import AsyncSession
from intric.database.transaction import gen_transaction
from intric.files.file_models import File, FilePublic
from intric.info_blobs.info_blob import (
    InfoBlobAskAssistantPublic,
    InfoBlobInDB,
    InfoBlobMetadata,
)
from intric.main.logging import get_logger
from intric.questions.question import UseTools, WebSearchResultPublic
from intric.sessions.session import (
    AskChatResponse,
    AskResponse,
    IntricEventType,
    SessionInDB,
    SSEFiles,
    SSEFirstChunk,
    SSEIntricEvent,
    SSEText,
    SSEToolApprovalRequired,
    SSEToolCall,
    SSEError,
    ToolCallInfo,
)

if TYPE_CHECKING:
    from uuid import UUID

    from intric.assistants.api.assistant_models import AssistantResponse

logger = get_logger(__name__)


def to_ask_response(
    question: str,
    files: list[File],
    session: SessionInDB,
    answer: str,
    info_blobs: list[InfoBlobInDB],
    completion_model: Optional[CompletionModel] = None,
    tools: "UseTools" = None,
):
    return AskResponse(
        question=question,
        files=[FilePublic(**file.model_dump()) for file in files],
        generated_files=[],
        session_id=session.id,
        answer=answer,
        references=[
            InfoBlobAskAssistantPublic(
                **blob.model_dump(),
                metadata=InfoBlobMetadata(**blob.model_dump()),
            )
            for blob in info_blobs
        ],
        model=completion_model,
        tools=tools,
        web_search_references=[],
    )


def to_ask_conversation_response(
    question: str,
    files: list[File],
    session: SessionInDB,
    answer: str,
    info_blobs: list[InfoBlobInDB],
    tools: "UseTools" = None,
    completion_model: Optional[CompletionModel] = None,
    question_id: Optional["UUID"] = None,
    created_at: Optional[datetime] = None,
    updated_at: Optional[datetime] = None,
    web_search_results: list[WebSearchResultPublic] = [],
):
    return AskChatResponse(
        created_at=created_at,
        updated_at=updated_at,
        session_id=session.id,
        id=question_id,
        completion_model=completion_model,
        files=[FilePublic(**file.model_dump()) for file in files],
        generated_files=[],
        question=question,
        answer=answer,
        references=[
            InfoBlobAskAssistantPublic(
                **blob.model_dump(),
                metadata=InfoBlobMetadata(**blob.model_dump()),
            )
            for blob in info_blobs
        ],
        tools=tools,
        web_search_references=[
            WebSearchResultPublic(
                id=web_search_result.id,
                title=web_search_result.title,
                url=web_search_result.url,
            )
            for web_search_result in web_search_results
        ],
    )


def to_sse_response(chunk: Completion, session_id: "UUID"):
    if chunk.response_type == ResponseType.TEXT:
        data = SSEText(
            session_id=session_id,
            answer=chunk.text,
            references=[
                InfoBlobAskAssistantPublic(
                    **blob.model_dump(),
                    metadata=InfoBlobMetadata(**blob.model_dump()),
                )
                for blob in chunk.reference_chunks
            ],
        )

    if chunk.response_type == ResponseType.FILES:
        data = SSEFiles(
            session_id=session_id,
            generated_files=[FilePublic(**chunk.generated_file.model_dump())],
        )

    if chunk.response_type == ResponseType.INTRIC_EVENT:
        data = SSEIntricEvent(
            session_id=session_id,
            intric_event_type=IntricEventType.GENERATING_IMAGE,
        )

    if chunk.response_type == ResponseType.TOOL_CALL:
        data = SSEToolCall(
            session_id=session_id,
            tools=[
                ToolCallInfo(server_name=tc.server_name, tool_name=tc.tool_name, arguments=tc.arguments)
                for tc in (chunk.tool_calls_metadata or [])
            ],
        )

    if chunk.response_type == ResponseType.TOOL_APPROVAL_REQUIRED:
        data = SSEToolApprovalRequired(
            session_id=session_id,
            approval_id=chunk.approval_id,
            tools=[
                ToolCallInfo(
                    server_name=tc.server_name,
                    tool_name=tc.tool_name,
                    arguments=tc.arguments,
                    tool_call_id=tc.tool_call_id,
                )
                for tc in (chunk.tool_calls_metadata or [])
            ],
        )

    if chunk.response_type == ResponseType.ERROR:
        data = SSEError(
            session_id=session_id,
            error=chunk.error,
            error_code=chunk.error_code,
        )

    return ServerSentEvent(data.model_dump_json(), event=chunk.response_type.value)


async def to_response(
    response: "AssistantResponse",
    db_session: AsyncSession,
    stream: bool,
):
    if stream:

        @gen_transaction(db_session)
        async def event_stream():
            async for chunk in response.answer:

                if chunk.response_type == ResponseType.TEXT:
                    yield to_ask_response(
                        question=response.question,
                        files=response.files,
                        session=response.session,
                        answer=chunk.text,
                        info_blobs=chunk.reference_chunks,
                        completion_model=response.completion_model,
                        tools=response.tools,
                    ).model_dump_json()

        return EventSourceResponse(event_stream())

    return to_ask_response(
        question=response.question,
        files=response.files,
        session=response.session,
        answer=response.answer,
        info_blobs=response.info_blobs,
        completion_model=response.completion_model,
        tools=response.tools,
    )


async def to_conversation_response(
    response: "AssistantResponse",
    db_session: AsyncSession,
    stream: bool,
):
    if stream:

        @gen_transaction(db_session)
        async def event_stream():
            data = SSEFirstChunk(
                **to_ask_conversation_response(
                    question=response.question,
                    files=response.files,
                    session=response.session,
                    answer="",
                    info_blobs=response.info_blobs,
                    tools=response.tools,
                    completion_model=response.completion_model,
                    question_id=response.question_id,
                    created_at=response.created_at,
                    updated_at=response.updated_at,
                    web_search_results=response.web_search_results,
                ).model_dump()
            )
            yield ServerSentEvent(
                data.model_dump_json(), event=ResponseType.FIRST_CHUNK.value
            )

            async for chunk in response.answer:
                yield to_sse_response(chunk=chunk, session_id=response.session.id)

        return EventSourceResponse(event_stream())

    return to_ask_conversation_response(
        question=response.question,
        files=response.files,
        session=response.session,
        answer=response.answer,
        info_blobs=response.info_blobs,
        tools=response.tools,
        completion_model=response.completion_model,
        question_id=response.question_id,
        created_at=response.created_at,
        updated_at=response.updated_at,
    )
