import json
from uuid import uuid4

import pytest

from intric.ai_models.completion_models.completion_model import (
    Completion,
    McpToolReference,
    ResponseType,
    ToolCallMetadata,
)
from intric.assistants.api.assistant_protocol import (
    to_ask_conversation_response,
    to_sse_response,
)
from intric.questions.question import UseTools
from intric.sessions.session import SessionInDB


def test_non_streaming_conversation_response_includes_mcp_references():
    reference = McpToolReference(
        id=uuid4(),
        tool_call_id="call_1",
        mcp_tool_name="server__tool",
        uri="https://example.test/resource",
        mime_type="text/plain",
        content="resource content",
        meta={"title": "Resource"},
        order=0,
    )

    response = to_ask_conversation_response(
        question="Question",
        files=[],
        session=SessionInDB(id=uuid4(), user_id=uuid4(), name="Conversation"),
        answer="Answer",
        info_blobs=[],
        tools=UseTools(assistants=[]),
        mcp_tool_references=[reference],
    )

    assert len(response.mcp_tool_references) == 1
    assert response.mcp_tool_references[0].id == reference.id
    assert response.mcp_tool_references[0].content == "resource content"


def test_tool_call_sse_preserves_null_tool_call_id():
    event = to_sse_response(
        Completion(
            response_type=ResponseType.TOOL_CALL,
            tool_calls_metadata=[
                ToolCallMetadata(
                    server_name="mcp",
                    tool_name="search",
                    tool_call_id=None,
                )
            ],
        ),
        uuid4(),
    )

    payload = json.loads(event.data)

    assert payload["tools"][0]["tool_call_id"] is None


def test_tool_approval_sse_requires_real_approval_id():
    with pytest.raises(ValueError, match="approval_id"):
        to_sse_response(
            Completion(
                response_type=ResponseType.TOOL_APPROVAL_REQUIRED,
                approval_id=None,
                tool_calls_metadata=[],
            ),
            uuid4(),
        )
