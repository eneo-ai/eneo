"""Golden-transcript test for the version=3 AI SDK UI Message Stream emitter.

Drives a scripted Completion sequence (text + references, generated image,
tool calls, approval pause/timeout, token usage, error) through the emitter
and asserts the exact UI Message Stream chunk sequence, including the
`data: [DONE]` terminator and the protocol marker header.
"""

import json
from uuid import UUID, uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelPublic,
    GeneratedFile,
    McpToolReference,
    ResponseType,
    TokenUsage,
    ToolCallMetadata,
)
from eneo.assistants.api.assistant_models import AssistantResponse
from eneo.conversations.ui_message_stream import (
    UI_MESSAGE_STREAM_HEADERS,
    _tool_chunks,
    _ui_message_chunks,
    to_ui_message_stream_response,
)
from eneo.files.file_models import File, FileType
from eneo.info_blobs.info_blob import InfoBlobInDBWithScore
from eneo.questions.question import UseTools
from eneo.sessions.session import SessionInDB

SESSION_ID = UUID("11111111-1111-1111-1111-111111111111")
QUESTION_ID = UUID("22222222-2222-2222-2222-222222222222")
BLOB_ID = UUID("33333333-3333-3333-3333-333333333333")


def test_tool_chunks_preserve_display_metadata_for_capability_and_skill_calls():
    calls = [
        ToolCallMetadata(
            server_name="External Images",
            tool_name="draw",
            title="Draw an image",
            purpose="image_generation",
            arguments={"prompt": "a lighthouse"},
            tool_call_id="image-call",
        ),
        ToolCallMetadata(
            server_name="skills",
            tool_name="planning",
            title="Planning Skill",
            arguments={"mode": "on_demand"},
            tool_call_id="skill-call",
        ),
    ]

    chunks = _tool_chunks(calls, {})

    assert chunks[0]["providerMetadata"]["eneo"] == {
        "server_name": "External Images",
        "title": "Draw an image",
        "purpose": "image_generation",
        "is_internal": None,
        "is_bundled": None,
        "app_view": None,
        "approved": None,
        "result_status": None,
    }
    assert chunks[1]["providerMetadata"]["eneo"]["title"] == "Planning Skill"


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
        source_id=uuid4(),
        version_state="active",
        original_available=True,
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


def _tool(
    status: str | None, tool_call_id: str = "call-1", approved: bool | None = None
) -> ToolCallMetadata:
    return ToolCallMetadata(
        server_name="files",
        tool_name="read_file",
        arguments={"path": "a.txt"},
        tool_call_id=tool_call_id,
        approved=approved,
        result_status=status,
        is_internal=True,
    )


def _mcp_reference(
    reference_id: UUID = UUID("44444444-4444-4444-4444-444444444444"),
) -> McpToolReference:
    return McpToolReference(
        id=reference_id,
        tool_call_id="call-1",
        mcp_tool_name="files__read_file",
        uri="mcp://files/a.txt",
        mime_type="text/markdown",
        content="resource content",
        meta={"title": "a.txt", "section": "Intro"},
        order=0,
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


def _announced(tool_call_id: str = "call-1") -> ToolCallMetadata:
    """A call as the adapter announces it, before its arguments are written."""
    return ToolCallMetadata(
        server_name="files",
        tool_name="read_file",
        arguments=None,
        tool_call_id=tool_call_id,
        result_status="pending",
        is_internal=True,
    )


def _delta(piece: str, tool_call_id: str = "call-1") -> Completion:
    return Completion(
        response_type=ResponseType.TOOL_CALL_DELTA,
        tool_call_id=tool_call_id,
        arguments_delta=piece,
    )


def _snapshot(*tools: ToolCallMetadata) -> Completion:
    return Completion(
        response_type=ResponseType.TOOL_CALL, tool_calls_metadata=list(tools)
    )


@pytest.mark.asyncio
async def test_announced_call_streams_its_input_before_it_is_available(caplog):
    completions = [
        _snapshot(_announced()),
        _delta('{"pa'),
        _delta('th": "a.txt"}'),
        _snapshot(_tool("pending")),
        _snapshot(_tool("succeeded")),
        Completion(response_type=ResponseType.TEXT, text="Done"),
    ]

    chunks = await _collect(_response(completions))
    tool_chunks = [c for c in chunks if c["type"].startswith("tool-")]

    assert [c["type"] for c in tool_chunks] == [
        "tool-input-start",
        "tool-input-delta",
        "tool-input-delta",
        "tool-input-available",
        "tool-output-available",
    ]
    start = tool_chunks[0]
    assert start["toolCallId"] == "call-1"
    assert start["toolName"] == "read_file"
    assert start["dynamic"] is True
    assert "input" not in start
    assert start["providerMetadata"]["eneo"]["result_status"] == "pending"
    assert [c["inputTextDelta"] for c in tool_chunks[1:3]] == ['{"pa', 'th": "a.txt"}']
    assert all(c["toolCallId"] == "call-1" for c in tool_chunks[1:3])
    assert tool_chunks[3]["input"] == {"path": "a.txt"}
    assert "Unsupported response type" not in caplog.text


@pytest.mark.asyncio
async def test_deltas_after_the_input_is_available_are_dropped():
    completions = [
        _snapshot(_announced()),
        _delta('{"path": "a.txt"}'),
        _snapshot(_tool("pending")),
        _delta(" "),
        # A repeated announcement never sends a known input back to streaming.
        _snapshot(_announced()),
        _snapshot(_tool("succeeded")),
    ]

    chunks = await _collect(_response(completions))

    assert [c["type"] for c in chunks if c["type"].startswith("tool-")] == [
        "tool-input-start",
        "tool-input-delta",
        "tool-input-available",
        "tool-output-available",
    ]


@pytest.mark.asyncio
async def test_deltas_for_a_call_never_announced_are_dropped():
    completions = [
        _delta('{"pa', tool_call_id="call-unknown"),
        _snapshot(_tool("pending")),
        _delta('th"}', tool_call_id="call-1"),
        Completion(response_type=ResponseType.TEXT, text="Done"),
    ]

    chunks = await _collect(_response(completions))

    assert [c["type"] for c in chunks] == [
        "start",
        "data-session",
        "tool-input-available",
        "text-start",
        "text-delta",
        "text-end",
        "finish",
    ]


@pytest.mark.asyncio
async def test_announced_call_that_fails_unwritten_still_gets_its_input_first():
    failed = _announced()
    failed.result_status = "failed"

    chunks = await _collect(_response([_snapshot(_announced()), _snapshot(failed)]))

    assert [c["type"] for c in chunks if c["type"].startswith("tool-")] == [
        "tool-input-start",
        "tool-input-available",
        "tool-output-error",
    ]
    assert chunks[3]["input"] == {}


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
async def test_reasoning_can_resume_after_text():
    completions = [
        Completion(response_type=ResponseType.TEXT, text="First"),
        Completion(
            response_type=ResponseType.REASONING, reasoning_content="Think again"
        ),
        Completion(response_type=ResponseType.TEXT, text="Second"),
    ]

    chunks = await _collect(_response(completions))
    types = [chunk["type"] for chunk in chunks]

    assert types == [
        "start",
        "data-session",
        "text-start",
        "text-delta",
        "text-end",
        "reasoning-start",
        "reasoning-delta",
        "reasoning-end",
        "text-start",
        "text-delta",
        "text-end",
        "finish",
    ]

    assert [c["id"] for c in chunks if c["type"] == "text-start"] == [
        "text-0",
        "text-1",
    ]
    assert [c["id"] for c in chunks if c["type"] == "reasoning-start"] == [
        "reasoning-0"
    ]


def _part_texts(chunks: list[dict], kind: str = "text") -> dict[str, str]:
    parts: dict[str, str] = {}
    for chunk in chunks:
        if chunk["type"] == f"{kind}-delta":
            parts[chunk["id"]] = parts.get(chunk["id"], "") + chunk["delta"]
    return parts


@pytest.mark.asyncio
async def test_round_break_stays_in_a_continuing_part_but_never_starts_one():
    # The adapter opens a later model round's text with a paragraph break.
    completions = [
        Completion(response_type=ResponseType.TEXT, text="Checking."),
        Completion(
            response_type=ResponseType.TOOL_CALL,
            tool_calls_metadata=[_tool(status="succeeded")],
        ),
        Completion(response_type=ResponseType.TEXT, text="\n\nFound it."),
        Completion(response_type=ResponseType.REASONING, reasoning_content="Again"),
        Completion(response_type=ResponseType.TEXT, text="\n\nAnswer"),
    ]

    chunks = await _collect(_response(completions))

    assert _part_texts(chunks) == {
        "text-0": "Checking.\n\nFound it.",
        "text-1": "Answer",
    }


@pytest.mark.asyncio
async def test_round_break_in_reasoning_follows_the_same_part_rules():
    # The adapter opens a later model round's reasoning with a paragraph break.
    completions = [
        Completion(response_type=ResponseType.REASONING, reasoning_content="Plan."),
        Completion(
            response_type=ResponseType.TOOL_CALL,
            tool_calls_metadata=[_tool(status="succeeded")],
        ),
        Completion(
            response_type=ResponseType.REASONING, reasoning_content="\n\nCheck."
        ),
        Completion(response_type=ResponseType.TEXT, text="Found it."),
        Completion(
            response_type=ResponseType.REASONING, reasoning_content="\n\nFormat."
        ),
        Completion(response_type=ResponseType.TEXT, text="\n\nDone."),
    ]

    chunks = await _collect(_response(completions))

    assert _part_texts(chunks, "reasoning") == {
        "reasoning-0": "Plan.\n\nCheck.",
        "reasoning-1": "Format.",
    }
    assert _part_texts(chunks) == {"text-0": "Found it.", "text-1": "Done."}


@pytest.mark.asyncio
async def test_later_text_part_opens_at_its_first_text():
    completions = [
        Completion(response_type=ResponseType.TEXT, text="First"),
        Completion(response_type=ResponseType.REASONING, reasoning_content="Hmm"),
        Completion(response_type=ResponseType.TEXT, text="\n"),
        Completion(response_type=ResponseType.TEXT, text="\nSecond"),
    ]

    chunks = await _collect(_response(completions))

    assert [chunk["type"] for chunk in chunks] == [
        "start",
        "data-session",
        "text-start",
        "text-delta",
        "text-end",
        "reasoning-start",
        "reasoning-delta",
        "reasoning-end",
        "text-start",
        "text-delta",
        "text-end",
        "finish",
    ]
    assert _part_texts(chunks) == {"text-0": "First", "text-1": "Second"}


@pytest.mark.asyncio
async def test_tool_calls_and_approval_pause_resume():
    completions = [
        Completion(
            response_type=ResponseType.TOOL_APPROVAL_REQUIRED,
            approval_id="approval-1",
            tool_calls_metadata=[_tool(status=None)],
        ),
        # Approval granted: the adapter answers with the decided snapshot, then
        # execution snapshots follow on the same stream.
        Completion(
            response_type=ResponseType.TOOL_CALL,
            tool_calls_metadata=[_tool(status="approved", approved=True)],
        ),
        Completion(
            response_type=ResponseType.TOOL_CALL,
            tool_calls_metadata=[_tool(status="succeeded", approved=True)],
        ),
        Completion(response_type=ResponseType.TEXT, text="Done"),
    ]

    chunks = await _collect(_response(completions))
    types = [chunk["type"] for chunk in chunks]

    assert types == [
        "start",
        "data-session",
        "data-tool-approval",
        "data-tool-approval",
        "tool-input-available",
        "tool-output-available",
        "text-start",
        "text-delta",
        "text-end",
        "finish",
    ]

    pending, decided = (c for c in chunks if c["type"] == "data-tool-approval")
    assert pending["id"] == decided["id"] == "approval-1"
    assert pending["data"]["status"] == "pending"
    assert pending["data"]["tools"][0]["tool_name"] == "read_file"
    assert decided["data"]["status"] == "approved"
    assert decided["data"]["tools"][0]["approved"] is True

    tool_input = next(c for c in chunks if c["type"] == "tool-input-available")
    assert tool_input["toolCallId"] == "call-1"
    assert tool_input["toolName"] == "read_file"
    assert tool_input["input"] == {"path": "a.txt"}
    assert tool_input["dynamic"] is True
    assert tool_input["providerMetadata"]["eneo"] == {
        "server_name": "files",
        "title": None,
        "purpose": None,
        "is_internal": True,
        "is_bundled": None,
        "app_view": None,
        "approved": True,
        "result_status": "approved",
    }

    tool_output = next(c for c in chunks if c["type"] == "tool-output-available")
    assert tool_output["toolCallId"] == "call-1"
    assert tool_output["output"] == {"status": "succeeded"}
    assert tool_output["providerMetadata"]["eneo"]["server_name"] == "files"


@pytest.mark.asyncio
async def test_tool_call_emits_mcp_resource_references():
    reference = _mcp_reference()
    completions = [
        Completion(
            response_type=ResponseType.TOOL_CALL,
            tool_calls_metadata=[_tool(status="succeeded")],
            mcp_tool_references=[reference],
        ),
        Completion(response_type=ResponseType.TEXT, text="Done"),
    ]

    chunks = await _collect(_response(completions))
    types = [chunk["type"] for chunk in chunks]

    assert types == [
        "start",
        "data-session",
        "data-mcp-tool-references",
        # A call seen for the first time announces its input before its output.
        "tool-input-available",
        "tool-output-available",
        "text-start",
        "text-delta",
        "text-end",
        "finish",
    ]

    references = next(c for c in chunks if c["type"] == "data-mcp-tool-references")
    assert references["data"]["mcp_tool_references"] == [
        {
            "id": str(reference.id),
            "uri": "mcp://files/a.txt",
            "mime_type": "text/markdown",
            "content": "resource content",
            "meta": {"title": "a.txt", "section": "Intro"},
            "tool_call_id": "call-1",
            "mcp_tool_name": "files__read_file",
        }
    ]


@pytest.mark.asyncio
async def test_denied_approval_resolves_part_and_announces_the_call_first():
    completions = [
        Completion(
            response_type=ResponseType.TOOL_APPROVAL_REQUIRED,
            approval_id="approval-3",
            tool_calls_metadata=[
                _tool(status=None),
                _tool(status=None, tool_call_id="call-2"),
            ],
        ),
        # A denied call reaches the stream as a terminal status without any
        # earlier execution snapshot.
        Completion(
            response_type=ResponseType.TOOL_CALL,
            tool_calls_metadata=[
                _tool(status="denied", approved=False),
                _tool(status="approved", approved=True, tool_call_id="call-2"),
            ],
        ),
    ]

    chunks = await _collect(_response(completions))
    types = [chunk["type"] for chunk in chunks]

    # The AI SDK rejects an output for a tool call it has not seen, so the
    # input phase always precedes the output phase of a call.
    assert types == [
        "start",
        "data-session",
        "data-tool-approval",
        "data-tool-approval",
        "tool-input-available",
        "tool-output-error",
        "tool-input-available",
        "finish",
    ]
    decided = [c for c in chunks if c["type"] == "data-tool-approval"][1]
    # One approved call: the run continues; per-call flags tell which.
    assert decided["data"]["status"] == "approved"
    assert [t["approved"] for t in decided["data"]["tools"]] == [False, True]
    error = next(c for c in chunks if c["type"] == "tool-output-error")
    assert error["toolCallId"] == "call-1"
    assert error["errorText"] == "denied"


@pytest.mark.asyncio
async def test_tool_metadata_carries_is_internal_from_the_routed_server():
    external = ToolCallMetadata(
        server_name="files",  # an admin-named external server, not the built-in one
        tool_name="read_file",
        tool_call_id="call-x",
        is_internal=False,
    )
    completions = [
        Completion(
            response_type=ResponseType.TOOL_APPROVAL_REQUIRED,
            approval_id="approval-4",
            tool_calls_metadata=[external],
        ),
    ]

    chunks = await _collect(_response(completions))
    approval = next(c for c in chunks if c["type"] == "data-tool-approval")
    assert approval["data"]["tools"][0]["is_internal"] is False
    assert (
        _tool_chunks([external], {})[0]["providerMetadata"]["eneo"]["is_internal"]
        is False
    )


def test_tool_metadata_carries_bundling_view_and_status_on_every_chunk():
    app_view = {
        "view_id": "view-1",
        "mcp_server_id": "server-1",
        "ui": {"prefersBorder": True},
    }
    call = ToolCallMetadata(
        server_name="documents",
        tool_name="create_document",
        title="Create a document",
        arguments={"title": "Plan"},
        tool_call_id="call-doc",
        approved=True,
        result_status="succeeded",
        is_internal=True,
        is_bundled=True,
        app_view=app_view,
    )

    chunks = _tool_chunks([call], {})

    assert [c["type"] for c in chunks] == [
        "tool-input-available",
        "tool-output-available",
    ]
    for chunk in chunks:
        eneo = chunk["providerMetadata"]["eneo"]
        assert list(eneo) == [
            "server_name",
            "title",
            "purpose",
            "is_internal",
            "is_bundled",
            "app_view",
            "approved",
            "result_status",
        ]
        assert eneo["is_bundled"] is True
        assert eneo["app_view"] == app_view
        assert eneo["approved"] is True
        assert eneo["result_status"] == "succeeded"

    announced = ToolCallMetadata(
        server_name="documents",
        tool_name="create_document",
        tool_call_id="call-doc",
        result_status="pending",
        is_bundled=True,
        app_view=app_view,
    )
    start = _tool_chunks([announced], {})[0]
    assert start["type"] == "tool-input-start"
    # The view is known before the arguments are.
    assert start["providerMetadata"]["eneo"]["app_view"] == app_view


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
async def test_generated_image():
    completions = [
        Completion(response_type=ResponseType.FILES, generated_file=_generated_file()),
    ]

    chunks = await _collect(_response(completions))
    types = [chunk["type"] for chunk in chunks]
    assert types == ["start", "data-session", "file", "finish"]

    file_chunk = chunks[2]
    assert file_chunk["mediaType"] == "image/png"
    assert file_chunk["filename"] == "generated.png"
    assert file_chunk["url"].startswith("http://backend:8123/api/v1/files/")
    assert "/download/?token=" in file_chunk["url"]
    # No producing call is known for a file that arrives without one.
    assert file_chunk["providerMetadata"]["eneo"]["tool_call_id"] is None


@pytest.mark.asyncio
async def test_file_chunk_names_the_tool_call_that_produced_it():
    generated = _generated_file()
    completions = [
        Completion(
            response_type=ResponseType.FILES,
            image=GeneratedFile(
                data=b"\x89PNG", mime_type="image/png", tool_call_id="call-7"
            ),
            generated_file=generated,
        ),
    ]

    chunks = await _collect(_response(completions))
    eneo = chunks[2]["providerMetadata"]["eneo"]

    assert eneo["tool_call_id"] == "call-7"
    assert eneo["id"] == str(generated.id)
    # The FilePublic keys come first, the producing call last.
    assert list(eneo)[-1] == "tool_call_id"


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
