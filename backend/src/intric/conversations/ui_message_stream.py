"""AI SDK UI Message Stream emitter (conversation stream version=3).

Maps the internal Completion chunk stream onto the Vercel AI SDK UI Message
Stream protocol (https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol): data-only
SSE events whose JSON carries a `type` discriminator, terminated by
`data: [DONE]`, with the `x-vercel-ai-ui-message-stream: v1` marker header.
version=1/2 framing (assistant_protocol.to_conversation_response) is untouched.

Custom data parts (consumed by the web-next chat UI):
- `data-session`: session id, completion model and uploaded files, replacing
  v2's first_chunk metadata.
- `data-status`: transient progress events (e.g. generating_image).
- `data-token-usage`: transient prompt/completion/turn token counts.
- `data-tool-approval`: MCP tool approval requests; reconciled in place by
  part id (the approval_id), so a timeout updates the pending part. The
  Redis-backed approval manager and POST /conversations/approve-tools/ are
  reused unchanged; the stream stays open while approval is pending.
"""

import json
import time
from typing import TYPE_CHECKING, Any, AsyncIterable, Optional
from uuid import uuid4

from sse_starlette import EventSourceResponse, ServerSentEvent

from intric.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelPublic,
    ResponseType,
)
from intric.authentication.signed_urls import generate_signed_token
from intric.completion_models.domain.completion_model import CompletionModel
from intric.files.file_models import ContentDisposition, FilePublic
from intric.info_blobs.info_blob import InfoBlobAskAssistantPublic, InfoBlobMetadata
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.ai_models.completion_models.completion_model import ToolCallMetadata
    from intric.assistants.api.assistant_models import AssistantResponse

logger = get_logger(__name__)

UI_MESSAGE_STREAM_HEADERS = {"x-vercel-ai-ui-message-stream": "v1"}

_GENERATED_FILE_URL_TTL_SECONDS = 60 * 60 * 24

# result_status values that mean the tool finished unsuccessfully (mapped to
# tool-output-error); "succeeded" maps to tool-output-available, anything else
# is still in the input phase.
_TOOL_ERROR_STATUSES = {"failed", "denied", "timeout_denied"}


def _event(chunk: dict[str, Any]) -> ServerSentEvent:
    return ServerSentEvent(json.dumps(chunk))


def _model_public(
    model: "CompletionModel | CompletionModelPublic | None",
) -> Optional[CompletionModelPublic]:
    if model is None or isinstance(model, CompletionModelPublic):
        return model
    return CompletionModelPublic.from_domain(model)


def _source_document_chunk(blob: Any) -> dict[str, Any]:
    public = InfoBlobAskAssistantPublic(
        **blob.model_dump(),
        metadata=InfoBlobMetadata(**blob.model_dump()),
    )
    return {
        "type": "source-document",
        "sourceId": str(public.id),
        "mediaType": "text/plain",
        "title": public.metadata.title or "",
        "providerMetadata": {
            "eneo": json.loads(public.model_dump_json()),
        },
    }


def _tool_chunks(
    tools: "list[ToolCallMetadata]", fallback_ids: dict[int, str]
) -> list[dict[str, Any]]:
    """Maps eneo tool-call metadata onto dynamic-tool chunks.

    The backend streams status snapshots (not tool outputs), so the output
    payload carries the execution status. Tool calls without a tool_call_id
    get a stable generated id per list position.
    """
    chunks: list[dict[str, Any]] = []
    for index, tool in enumerate(tools):
        tool_call_id = tool.tool_call_id or fallback_ids.setdefault(index, str(uuid4()))
        base = {
            "toolCallId": tool_call_id,
            "dynamic": True,
        }
        status = tool.result_status
        if status == "succeeded":
            chunks.append(
                {"type": "tool-output-available", "output": {"status": status}, **base}
            )
        elif status in _TOOL_ERROR_STATUSES:
            chunks.append({"type": "tool-output-error", "errorText": status, **base})
        else:
            chunks.append(
                {
                    "type": "tool-input-available",
                    "toolName": tool.tool_name,
                    "input": tool.arguments or {},
                    "providerMetadata": {"eneo": {"server_name": tool.server_name}},
                    **base,
                }
            )
    return chunks


def _tool_approval_chunk(
    approval_id: str, tools: "list[ToolCallMetadata]", status: str
) -> dict[str, Any]:
    return {
        "type": "data-tool-approval",
        "id": approval_id,
        "data": {
            "approval_id": approval_id,
            "status": status,
            "tools": [
                {
                    "server_name": tool.server_name,
                    "tool_name": tool.tool_name,
                    "arguments": tool.arguments,
                    "tool_call_id": tool.tool_call_id,
                    "approved": tool.approved,
                    "result_status": tool.result_status,
                }
                for tool in tools
            ],
        },
    }


def _generated_file_chunk(file: Any, base_url: str) -> dict[str, Any]:
    public = FilePublic(**file.model_dump())
    expires_at = int(time.time()) + _GENERATED_FILE_URL_TTL_SECONDS
    token = generate_signed_token(
        file_id=public.id,
        expires_at=expires_at,
        content_disposition=ContentDisposition.INLINE,
    )
    url = f"{base_url.rstrip('/')}/api/v1/files/{public.id}/download/?token={token}"
    return {
        "type": "file",
        "url": url,
        "mediaType": public.mimetype,
        "providerMetadata": {"eneo": json.loads(public.model_dump_json())},
    }


async def _ui_message_chunks(
    response: "AssistantResponse", base_url: str
) -> AsyncIterable[dict[str, Any]]:
    yield {"type": "start", "messageId": str(response.question_id or uuid4())}

    model = _model_public(response.completion_model)
    yield {
        "type": "data-session",
        "data": {
            "session_id": str(response.session.id),
            "completion_model": (
                json.loads(model.model_dump_json()) if model else None
            ),
            "files": [
                json.loads(FilePublic(**file.model_dump()).model_dump_json())
                for file in response.files
            ],
            "web_search_references": [
                {"id": str(result.id), "title": result.title, "url": result.url}
                for result in response.web_search_results
            ],
            # Group chat stamps the answering member assistant onto the response;
            # the single-assistant / clarification paths leave it empty.
            "answering_assistant": (
                {
                    "id": str(response.tools.assistants[0].id),
                    "handle": response.tools.assistants[0].handle,
                }
                if response.tools and response.tools.assistants
                else None
            ),
        },
    }

    # Pre-retrieved references (RAG happens before generation starts).
    seen_source_ids: set[str] = set()
    for blob in response.info_blobs:
        chunk_dict = _source_document_chunk(blob)
        if chunk_dict["sourceId"] not in seen_source_ids:
            seen_source_ids.add(chunk_dict["sourceId"])
            yield chunk_dict

    text_id: Optional[str] = None
    reasoning_id: Optional[str] = None
    reasoning_open = False
    tool_fallback_ids: dict[int, str] = {}
    emitted_tool_chunks: set[str] = set()

    assert not isinstance(response.answer, str)
    completion_stream: AsyncIterable[Completion] = response.answer
    async for completion in completion_stream:
        response_type = completion.response_type

        if response_type == ResponseType.REASONING:
            if reasoning_id is None:
                reasoning_id = "reasoning-0"
                reasoning_open = True
                yield {"type": "reasoning-start", "id": reasoning_id}
            if completion.reasoning_content:
                yield {
                    "type": "reasoning-delta",
                    "id": reasoning_id,
                    "delta": completion.reasoning_content,
                }

        elif response_type == ResponseType.TEXT:
            # Reasoning always precedes the answer; close it before text opens.
            if reasoning_open and reasoning_id is not None:
                yield {"type": "reasoning-end", "id": reasoning_id}
                reasoning_open = False
            if text_id is None:
                text_id = "text-0"
                yield {"type": "text-start", "id": text_id}
            if completion.text:
                yield {"type": "text-delta", "id": text_id, "delta": completion.text}
            for blob in completion.reference_chunks or []:
                chunk_dict = _source_document_chunk(blob)
                if chunk_dict["sourceId"] not in seen_source_ids:
                    seen_source_ids.add(chunk_dict["sourceId"])
                    yield chunk_dict

        elif response_type == ResponseType.FILES:
            assert completion.generated_file is not None
            yield _generated_file_chunk(completion.generated_file, base_url)

        elif response_type == ResponseType.INTRIC_EVENT:
            yield {
                "type": "data-status",
                "data": {"status": "generating_image"},
                "transient": True,
            }

        elif response_type == ResponseType.TOOL_CALL:
            for chunk_dict in _tool_chunks(
                list(completion.tool_calls_metadata or []), tool_fallback_ids
            ):
                # Tool snapshots repeat; emit each (id, phase) transition once.
                key = f"{chunk_dict['toolCallId']}:{chunk_dict['type']}"
                if key not in emitted_tool_chunks:
                    emitted_tool_chunks.add(key)
                    yield chunk_dict

        elif response_type == ResponseType.TOOL_APPROVAL_REQUIRED:
            assert completion.approval_id is not None
            yield _tool_approval_chunk(
                approval_id=completion.approval_id,
                tools=list(completion.tool_calls_metadata or []),
                status="pending",
            )

        elif response_type == ResponseType.TOOL_APPROVAL_TIMEOUT:
            assert completion.approval_id is not None
            yield _tool_approval_chunk(
                approval_id=completion.approval_id,
                tools=list(completion.tool_calls_metadata or []),
                status="timeout_denied",
            )

        elif response_type == ResponseType.TOKEN_USAGE:
            prompt = completion.usage.prompt_tokens or 0 if completion.usage else 0
            generated = (
                completion.usage.completion_tokens or 0 if completion.usage else 0
            )
            yield {
                "type": "data-token-usage",
                "data": {
                    "prompt_tokens": prompt,
                    "completion_tokens": generated,
                    "turn_tokens": prompt + generated,
                },
                "transient": True,
            }

        elif response_type == ResponseType.ERROR:
            yield {
                "type": "data-error",
                "data": {"code": completion.error_code},
                "transient": True,
            }
            yield {"type": "error", "errorText": completion.error or ""}

        else:
            logger.warning(
                "Unsupported response type in v3 stream",
                extra={"response_type": response_type.value if response_type else None},
            )

    if reasoning_open and reasoning_id is not None:
        yield {"type": "reasoning-end", "id": reasoning_id}
    if text_id is not None:
        yield {"type": "text-end", "id": text_id}
    yield {"type": "finish"}


def to_ui_message_stream_response(
    response: "AssistantResponse", base_url: str
) -> EventSourceResponse:
    """version=3 streaming response: AI SDK UI Message Stream over SSE."""

    async def event_stream():
        async for chunk in _ui_message_chunks(response, base_url):
            yield _event(chunk)
        yield ServerSentEvent("[DONE]")

    return EventSourceResponse(
        event_stream(), ping=15, headers=dict(UI_MESSAGE_STREAM_HEADERS)
    )
