"""Golden-transcript test for the version=3 AI SDK UI Message Stream emitter.

Drives a scripted Completion sequence (text + references, generated image,
tool calls, approval pause/timeout, token usage, error) through the emitter
and asserts the exact UI Message Stream chunk sequence, including the
`data: [DONE]` terminator and the protocol marker header.
"""

import json
from uuid import UUID, uuid4

import pytest

from intric.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelPublic,
    ResponseType,
    TokenUsage,
    ToolCallMetadata,
)
from intric.assistants.api.assistant_models import AssistantResponse
from intric.conversations.ui_message_stream import (
    UI_MESSAGE_STREAM_HEADERS,
    _ui_message_chunks,
    to_ui_message_stream_response,
)
from intric.files.file_models import File, FileType
from intric.info_blobs.info_blob import InfoBlobInDBWithScore
from intric.questions.question import UseTools
from intric.sessions.session import SessionInDB

SESSION_ID = UUID("11111111-1111-1111-1111-111111111111")
QUESTION_ID = UUID("22222222-2222-2222-2222-222222222222")
BLOB_ID = UUID("33333333-3333-3333-3333-333333333333")


def _completion_model() -> CompletionModelPublic:
    return CompletionModelPublic(
        id=uuid4(),
        name="mock-model",
        max_input_tokens=10_000,
        max_output_tokens=4_000,
        is_deprecated=False,
        vision=False,
        reasoning=False,
    )


def _blob(blob_id: UUID = BLOB_ID) -> InfoBlobInDBWithScore:
    return InfoBlobInDBWithScore(
        id=blob_id,
        title="Reference title",
        text="reference text",
        embedding_model_id=uuid4(),
        user_id=uuid4(),
        tenant_id=uuid4(),
        size=42,
        score=0.87,
    )


def _generated_file() -> File:
    return File(
        id=uuid4(),
        name="generated.png",
        checksum="abc",
        size=10,
        mimetype="image/png",
        file_type=FileType.IMAGE,
        blob=b"\x89PNG",
        user_id=uuid4(),
        tenant_id=uuid4(),
    )


def _tool(status: str | None, tool_call_id: str = "call-1") -> ToolCallMetadata:
    return ToolCallMetadata(
        server_name="files",
        tool_name="read_file",
        arguments={"path": "a.txt"},
        tool_call_id=tool_call_id,
        approved=None,
        result_status=status,
    )


def _response(completions: list[Completion]) -> AssistantResponse:
    async def stream():
        for completion in completions:
            yield completion

    return AssistantResponse(
        session=SessionInDB(id=SESSION_ID, name="Test session", user_id=uuid4()),
        question="What is in a.txt?",
        question_id=QUESTION_ID,
        files=[],
        answer=stream(),
        info_blobs=[],
        completion_model=_completion_model(),
        tools=UseTools(assistants=[]),
        web_search_results=[],
    )


async def _collect(response: AssistantResponse) -> list[dict]:
    return [
        chunk
        async for chunk in _ui_message_chunks(response, base_url="http://backend:8123/")
    ]


@pytest.mark.asyncio
async def test_golden_transcript():
    completions = [
        Completion(response_type=ResponseType.TEXT, text="Hel"),
        Completion(
            response_type=ResponseType.TEXT,
            text="lo",
            reference_chunks=[_blob()],
        ),
        # Snapshot resends the same reference: must not be re-emitted.
        Completion(
            response_type=ResponseType.TEXT,
            text="!",
            reference_chunks=[_blob()],
        ),
        Completion(
            response_type=ResponseType.TOKEN_USAGE,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
        ),
    ]

    chunks = await _collect(_response(completions))
    types = [chunk["type"] for chunk in chunks]

    assert types == [
        "start",
        "data-session",
        "text-start",
        "text-delta",
        "text-delta",
        "source-document",
        "text-delta",
        "data-token-usage",
        "text-end",
        "finish",
    ]

    assert chunks[0]["messageId"] == str(QUESTION_ID)

    session_data = chunks[1]["data"]
    assert session_data["session_id"] == str(SESSION_ID)
    assert session_data["completion_model"]["name"] == "mock-model"

    assert [c["delta"] for c in chunks if c["type"] == "text-delta"] == [
        "Hel",
        "lo",
        "!",
    ]
    text_ids = {c["id"] for c in chunks if c["type"].startswith("text-")}
    assert len(text_ids) == 1

    source = next(c for c in chunks if c["type"] == "source-document")
    assert source["sourceId"] == str(BLOB_ID)
    assert source["title"] == "Reference title"
    assert source["providerMetadata"]["eneo"]["score"] == 0.87

    usage = next(c for c in chunks if c["type"] == "data-token-usage")
    assert usage["transient"] is True
    assert usage["data"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "turn_tokens": 15,
    }


@pytest.mark.asyncio
async def test_reasoning_precedes_text():
    completions = [
        Completion(response_type=ResponseType.REASONING, reasoning_content="Let me "),
        Completion(response_type=ResponseType.REASONING, reasoning_content="think."),
        Completion(response_type=ResponseType.TEXT, text="Answer"),
    ]

    chunks = await _collect(_response(completions))
    types = [chunk["type"] for chunk in chunks]

    assert types == [
        "start",
        "data-session",
        "reasoning-start",
        "reasoning-delta",
        "reasoning-delta",
        "reasoning-end",
        "text-start",
        "text-delta",
        "text-end",
        "finish",
    ]

    # A single reasoning block id spans all reasoning chunks.
    reasoning_ids = {c["id"] for c in chunks if c["type"].startswith("reasoning-")}
    assert len(reasoning_ids) == 1
    assert [c["delta"] for c in chunks if c["type"] == "reasoning-delta"] == [
        "Let me ",
        "think.",
    ]


@pytest.mark.asyncio
async def test_reasoning_only_closes_without_text():
    completions = [
        Completion(response_type=ResponseType.REASONING, reasoning_content="hmm"),
    ]

    chunks = await _collect(_response(completions))
    types = [chunk["type"] for chunk in chunks]

    assert types == [
        "start",
        "data-session",
        "reasoning-start",
        "reasoning-delta",
        "reasoning-end",
        "finish",
    ]


@pytest.mark.asyncio
async def test_tool_calls_and_approval_pause_resume():
    completions = [
        Completion(
            response_type=ResponseType.TOOL_APPROVAL_REQUIRED,
            approval_id="approval-1",
            tool_calls_metadata=[_tool(status=None)],
        ),
        # Approval granted: execution snapshots follow on the same stream.
        Completion(
            response_type=ResponseType.TOOL_CALL,
            tool_calls_metadata=[_tool(status=None)],
        ),
        Completion(
            response_type=ResponseType.TOOL_CALL,
            tool_calls_metadata=[_tool(status="succeeded")],
        ),
        Completion(response_type=ResponseType.TEXT, text="Done"),
    ]

    chunks = await _collect(_response(completions))
    types = [chunk["type"] for chunk in chunks]

    assert types == [
        "start",
        "data-session",
        "data-tool-approval",
        "tool-input-available",
        "tool-output-available",
        "text-start",
        "text-delta",
        "text-end",
        "finish",
    ]

    approval = next(c for c in chunks if c["type"] == "data-tool-approval")
    assert approval["id"] == "approval-1"
    assert approval["data"]["status"] == "pending"
    assert approval["data"]["tools"][0]["tool_name"] == "read_file"

    tool_input = next(c for c in chunks if c["type"] == "tool-input-available")
    assert tool_input["toolCallId"] == "call-1"
    assert tool_input["toolName"] == "read_file"
    assert tool_input["input"] == {"path": "a.txt"}
    assert tool_input["dynamic"] is True

    tool_output = next(c for c in chunks if c["type"] == "tool-output-available")
    assert tool_output["toolCallId"] == "call-1"
    assert tool_output["output"] == {"status": "succeeded"}


@pytest.mark.asyncio
async def test_approval_timeout_updates_part_in_place():
    completions = [
        Completion(
            response_type=ResponseType.TOOL_APPROVAL_REQUIRED,
            approval_id="approval-2",
            tool_calls_metadata=[_tool(status=None)],
        ),
        Completion(
            response_type=ResponseType.TOOL_APPROVAL_TIMEOUT,
            approval_id="approval-2",
            tool_calls_metadata=[_tool(status="timeout_denied")],
        ),
    ]

    chunks = await _collect(_response(completions))
    approvals = [c for c in chunks if c["type"] == "data-tool-approval"]

    assert len(approvals) == 2
    # Same part id: the client reconciles the pending part in place.
    assert approvals[0]["id"] == approvals[1]["id"] == "approval-2"
    assert approvals[0]["data"]["status"] == "pending"
    assert approvals[1]["data"]["status"] == "timeout_denied"


@pytest.mark.asyncio
async def test_failed_tool_maps_to_output_error():
    completions = [
        Completion(
            response_type=ResponseType.TOOL_CALL,
            tool_calls_metadata=[_tool(status=None)],
        ),
        Completion(
            response_type=ResponseType.TOOL_CALL,
            tool_calls_metadata=[_tool(status="failed")],
        ),
    ]

    chunks = await _collect(_response(completions))
    error = next(c for c in chunks if c["type"] == "tool-output-error")
    assert error["toolCallId"] == "call-1"
    assert error["errorText"] == "failed"


@pytest.mark.asyncio
async def test_generated_image_and_status_event():
    completions = [
        Completion(response_type=ResponseType.INTRIC_EVENT),
        Completion(response_type=ResponseType.FILES, generated_file=_generated_file()),
    ]

    chunks = await _collect(_response(completions))
    types = [chunk["type"] for chunk in chunks]
    assert types == ["start", "data-session", "data-status", "file", "finish"]

    status = chunks[2]
    assert status["data"] == {"status": "generating_image"}
    assert status["transient"] is True

    file_chunk = chunks[3]
    assert file_chunk["mediaType"] == "image/png"
    assert file_chunk["url"].startswith("http://backend:8123/api/v1/files/")
    assert "/download/?token=" in file_chunk["url"]


@pytest.mark.asyncio
async def test_error_chunk():
    completions = [
        Completion(response_type=ResponseType.TEXT, text="partial"),
        Completion(
            response_type=ResponseType.ERROR,
            error="Model exploded",
            error_code=9024,
        ),
    ]

    chunks = await _collect(_response(completions))
    error = next(c for c in chunks if c["type"] == "error")
    assert error["errorText"] == "Model exploded"
    data_error = next(c for c in chunks if c["type"] == "data-error")
    assert data_error["data"]["code"] == 9024
    # The text block still closes and the stream finishes cleanly.
    assert [c["type"] for c in chunks[-2:]] == ["text-end", "finish"]


@pytest.mark.asyncio
async def test_sse_framing_and_headers():
    response = to_ui_message_stream_response(
        _response([Completion(response_type=ResponseType.TEXT, text="Hi")]),
        base_url="http://backend:8123/",
    )

    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
    assert UI_MESSAGE_STREAM_HEADERS["x-vercel-ai-ui-message-stream"] == "v1"
    assert response.headers["content-type"].startswith("text/event-stream")

    events = [event async for event in response.body_iterator]
    # Data-only SSE: every event is `data: {json}` and the last is [DONE].
    payloads = []
    for event in events:
        encoded = event.encode() if hasattr(event, "encode") else event
        text = encoded.decode() if isinstance(encoded, bytes) else str(encoded)
        assert text.startswith("data: ")
        payloads.append(text.removeprefix("data: ").strip())

    assert payloads[-1] == "[DONE]"
    parsed = [json.loads(payload) for payload in payloads[:-1]]
    assert parsed[0]["type"] == "start"
    assert parsed[-1]["type"] == "finish"
