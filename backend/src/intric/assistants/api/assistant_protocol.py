from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional, Protocol, cast

from sse_starlette import EventSourceResponse, ServerSentEvent

from intric.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelPublic,
    McpToolReference,
    ResponseType,
)
from intric.completion_models.domain.completion_model import CompletionModel
from intric.files.file_models import File, FilePublic
from intric.info_blobs.info_blob import (
    InfoBlobAskAssistantPublic,
    InfoBlobMetadata,
)
from intric.main.logging import get_logger
from intric.questions.question import (
    McpToolReferencePublic,
    UseTools,
    WebSearchResultPublic,
)
from intric.sessions.session import (
    AskChatResponse,
    AskResponse,
    IntricEventType,
    SessionInDB,
    SSEError,
    SSEFiles,
    SSEFirstChunk,
    SSEIntricEvent,
    SSEReasoning,
    SSEText,
    SSETokenUsage,
    SSEToolApprovalRequired,
    SSEToolApprovalTimeout,
    SSEToolCall,
    TokenUsageEvent,
    ToolCallInfo,
)

if TYPE_CHECKING:
    from uuid import UUID

    from intric.assistants.api.assistant_models import AssistantResponse

logger = get_logger(__name__)


class _SupportsModelDump(Protocol):
    def model_dump(self) -> dict[str, Any]: ...


class _SupportsWebSearchResult(Protocol):
    id: Any
    title: str
    url: str


class _SupportsToolCallMetadata(Protocol):
    server_name: str
    tool_name: str
    title: str | None
    arguments: dict[str, object] | None
    tool_call_id: str | None
    approved: bool | None
    result_status: str | None
    result: str | None
    mcp_tool_name: str | None


def _require_approval_id(chunk: Completion) -> str:
    if chunk.approval_id is None:
        raise ValueError("Expected approval_id for tool approval SSE event")
    return chunk.approval_id


def to_ask_response(
    question: str,
    files: Sequence[File],
    session: SessionInDB,
    answer: str,
    info_blobs: Sequence[_SupportsModelDump],
    tools: "UseTools",
    completion_model: CompletionModel | CompletionModelPublic | None = None,
    show_pricing: bool = True,
    mcp_tool_references: Sequence[McpToolReference] = (),
) -> AskResponse:
    if completion_model is None:
        public_model = None
    elif isinstance(completion_model, CompletionModelPublic):
        public_model = (
            completion_model
            if show_pricing
            else completion_model.model_copy(
                update={"input_cost_per_token": None, "output_cost_per_token": None}
            )
        )
    else:
        public_model = CompletionModelPublic.from_domain(
            completion_model, show_pricing=show_pricing
        )
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
        model=public_model,
        tools=tools,
        web_search_references=[],
        mcp_tool_references=[
            McpToolReferencePublic(
                id=ref.id,
                uri=ref.uri,
                mime_type=ref.mime_type,
                content=ref.content,
                meta=ref.meta,
                tool_call_id=ref.tool_call_id,
                mcp_tool_name=ref.mcp_tool_name,
            )
            for ref in mcp_tool_references
        ],
    )


def to_ask_conversation_response(
    question: str,
    files: Sequence[File],
    session: SessionInDB,
    answer: str,
    info_blobs: Sequence[_SupportsModelDump],
    tools: "UseTools",
    completion_model: CompletionModel | CompletionModelPublic | None = None,
    show_pricing: bool = True,
    question_id: Optional["UUID"] = None,
    created_at: Optional[datetime] = None,
    updated_at: Optional[datetime] = None,
    web_search_results: Sequence[_SupportsWebSearchResult] | None = None,
    mcp_tool_references: Sequence[McpToolReference] = (),
) -> AskChatResponse:
    if completion_model is None:
        public_model = None
    elif isinstance(completion_model, CompletionModelPublic):
        public_model = (
            completion_model
            if show_pricing
            else completion_model.model_copy(
                update={"input_cost_per_token": None, "output_cost_per_token": None}
            )
        )
    else:
        public_model = CompletionModelPublic.from_domain(
            completion_model, show_pricing=show_pricing
        )
    return AskChatResponse(  # type: ignore[call-arg]
        created_at=created_at,  # type: ignore[call-arg]
        updated_at=updated_at,  # type: ignore[call-arg]
        session_id=session.id,
        id=question_id,  # type: ignore[call-arg]
        completion_model=public_model,  # type: ignore[call-arg]
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
            for web_search_result in (web_search_results or [])
        ],
        mcp_tool_references=[
            McpToolReferencePublic(
                id=ref.id,
                uri=ref.uri,
                mime_type=ref.mime_type,
                content=ref.content,
                meta=ref.meta,
                tool_call_id=ref.tool_call_id,
                mcp_tool_name=ref.mcp_tool_name,
            )
            for ref in mcp_tool_references
        ],
    )


def to_sse_response(chunk: Completion, session_id: "UUID") -> ServerSentEvent:
    if chunk.response_type == ResponseType.TEXT:
        data = SSEText(
            session_id=session_id,
            answer=chunk.text or "",
            references=[
                InfoBlobAskAssistantPublic(
                    **blob.model_dump(),
                    metadata=InfoBlobMetadata(**blob.model_dump()),
                )
                for blob in (chunk.reference_chunks or [])
            ],
        )

    elif chunk.response_type == ResponseType.REASONING:
        data = SSEReasoning(
            session_id=session_id,
            reasoning=chunk.reasoning_content or "",
        )

    elif chunk.response_type == ResponseType.FILES:
        assert chunk.generated_file is not None
        data = SSEFiles(
            session_id=session_id,
            generated_files=[FilePublic(**chunk.generated_file.model_dump())],
        )

    elif chunk.response_type == ResponseType.INTRIC_EVENT:
        data = SSEIntricEvent(
            session_id=session_id,
            intric_event_type=IntricEventType.GENERATING_IMAGE,
        )

    elif chunk.response_type == ResponseType.TOOL_CALL:
        tool_calls = cast(
            Sequence[_SupportsToolCallMetadata], chunk.tool_calls_metadata or []
        )
        # `result` is intentionally omitted from the SSE payload — tool
        # outputs can be large and only a niche view ("Visa svar") needs
        # them. Frontend lazy-fetches via the tool-call-result endpoint
        # when the user expands the panel; conversation history likewise
        # omits the result and uses the same endpoint.
        data = SSEToolCall(
            session_id=session_id,
            tools=[
                ToolCallInfo(
                    server_name=tc.server_name,
                    tool_name=tc.tool_name,
                    title=tc.title,
                    arguments=tc.arguments,
                    tool_call_id=tc.tool_call_id,
                    approved=tc.approved,
                    result_status=tc.result_status,
                    mcp_tool_name=tc.mcp_tool_name,
                )
                for tc in tool_calls
            ],
            mcp_tool_references=[
                McpToolReferencePublic(
                    id=ref.id,
                    uri=ref.uri,
                    mime_type=ref.mime_type,
                    content=ref.content,
                    meta=ref.meta,
                    tool_call_id=ref.tool_call_id,
                    mcp_tool_name=ref.mcp_tool_name,
                )
                for ref in (chunk.mcp_tool_references or [])
            ],
        )

    elif chunk.response_type == ResponseType.TOOL_APPROVAL_REQUIRED:
        tool_calls = cast(
            Sequence[_SupportsToolCallMetadata], chunk.tool_calls_metadata or []
        )
        data = SSEToolApprovalRequired(
            session_id=session_id,
            approval_id=_require_approval_id(chunk),
            tools=[
                ToolCallInfo(
                    server_name=tc.server_name,
                    tool_name=tc.tool_name,
                    title=tc.title,
                    arguments=tc.arguments,
                    tool_call_id=tc.tool_call_id,
                    approved=tc.approved,
                    result_status=tc.result_status,
                )
                for tc in tool_calls
            ],
        )

    elif chunk.response_type == ResponseType.TOOL_APPROVAL_TIMEOUT:
        tool_calls = cast(
            Sequence[_SupportsToolCallMetadata], chunk.tool_calls_metadata or []
        )
        data = SSEToolApprovalTimeout(
            session_id=session_id,
            approval_id=_require_approval_id(chunk),
            tools=[
                ToolCallInfo(
                    server_name=tc.server_name,
                    tool_name=tc.tool_name,
                    title=tc.title,
                    arguments=tc.arguments,
                    tool_call_id=tc.tool_call_id,
                    approved=tc.approved,
                    result_status=tc.result_status,
                )
                for tc in tool_calls
            ],
        )

    elif chunk.response_type == ResponseType.TOKEN_USAGE:
        prompt = chunk.usage.prompt_tokens or 0 if chunk.usage else 0
        completion = chunk.usage.completion_tokens or 0 if chunk.usage else 0
        data = SSETokenUsage(
            session_id=session_id,
            usage=TokenUsageEvent(
                prompt_tokens=prompt,
                completion_tokens=completion,
                turn_tokens=prompt + completion,
            ),
        )

    elif chunk.response_type == ResponseType.ERROR:
        data = SSEError(
            session_id=session_id,
            error=chunk.error or "",
            error_code=chunk.error_code,
        )

    else:
        logger.warning(
            "Unsupported SSE response type",
            extra={
                "response_type": chunk.response_type.value
                if chunk.response_type
                else None
            },
        )
        data = SSEError(
            session_id=session_id,
            error="Unsupported response type",
            error_code=500,
        )

    event_name = (
        chunk.response_type.value
        if chunk.response_type is not None
        else ResponseType.ERROR.value
    )
    return ServerSentEvent(data.model_dump_json(), event=event_name)


async def to_response(
    response: "AssistantResponse",
    stream: bool,
    *,
    show_pricing: bool = True,
) -> EventSourceResponse | AskResponse:
    if stream:

        async def event_stream():
            assert not isinstance(response.answer, str)
            async for chunk in response.answer:
                if chunk.response_type == ResponseType.TEXT:
                    yield to_ask_response(
                        question=response.question,
                        files=response.files,
                        session=response.session,
                        answer=chunk.text or "",
                        info_blobs=chunk.reference_chunks or [],
                        completion_model=response.completion_model,
                        show_pricing=show_pricing,
                        tools=response.tools,
                    ).model_dump_json()

        return EventSourceResponse(event_stream(), ping=15)

    assert isinstance(response.answer, str)
    return to_ask_response(
        question=response.question,
        files=response.files,
        session=response.session,
        answer=response.answer,
        info_blobs=response.info_blobs,
        completion_model=response.completion_model,
        show_pricing=show_pricing,
        tools=response.tools,
        mcp_tool_references=response.mcp_tool_references,
    )


async def to_conversation_response(
    response: "AssistantResponse",
    stream: bool,
    *,
    show_pricing: bool = True,
) -> EventSourceResponse | AskChatResponse:
    if stream:

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
                    show_pricing=show_pricing,
                    question_id=response.question_id,
                    created_at=response.created_at,
                    updated_at=response.updated_at,
                    web_search_results=response.web_search_results,
                ).model_dump()
            )
            yield ServerSentEvent(
                data.model_dump_json(), event=ResponseType.FIRST_CHUNK.value
            )

            assert not isinstance(response.answer, str)
            async for chunk in response.answer:
                yield to_sse_response(chunk=chunk, session_id=response.session.id)

        return EventSourceResponse(event_stream(), ping=15)

    assert isinstance(response.answer, str)
    return to_ask_conversation_response(
        question=response.question,
        files=response.files,
        session=response.session,
        answer=response.answer,
        info_blobs=response.info_blobs,
        tools=response.tools,
        completion_model=response.completion_model,
        show_pricing=show_pricing,
        question_id=response.question_id,
        created_at=response.created_at,
        updated_at=response.updated_at,
        web_search_results=response.web_search_results,
        mcp_tool_references=response.mcp_tool_references,
    )
