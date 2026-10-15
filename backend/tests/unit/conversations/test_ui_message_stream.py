"""A server's progress for a running tool call reaches the UI message
stream as a transient data part keyed by the call."""

from __future__ import annotations

from uuid import UUID, uuid4

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelPublic,
    ResponseType,
)
from eneo.assistants.api.assistant_models import AssistantResponse
from eneo.conversations.ui_message_stream import _ui_message_chunks
from eneo.questions.question import UseTools
from eneo.sessions.session import SessionInDB


def _response(completions: list[Completion]) -> AssistantResponse:
    async def stream():
        for completion in completions:
            yield completion

    return AssistantResponse(
        session=SessionInDB(id=uuid4(), name="Test session", user_id=uuid4()),
        question="Summarise everything",
        question_id=uuid4(),
        files=[],
        answer=stream(),
        info_blobs=[],
        completion_model=CompletionModelPublic(
            id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            name="mock-model",
            nickname="Mock",
            max_input_tokens=10_000,
            max_output_tokens=4_000,
            is_deprecated=False,
            vision=False,
            reasoning=False,
        ),
        tools=UseTools(assistants=[]),
    )


async def test_tool_progress_is_a_transient_data_part_keyed_by_the_call():
    completions = [
        Completion(
            response_type=ResponseType.TOOL_PROGRESS,
            tool_call_id="call-1",
            progress=12,
            progress_total=44,
            progress_message="Read 12 of 44 parts",
        ),
        Completion(response_type=ResponseType.TEXT, text="Done"),
    ]

    chunks = [
        chunk
        async for chunk in _ui_message_chunks(
            _response(completions), base_url="http://backend:8123/"
        )
    ]

    progress = [c for c in chunks if c["type"] == "data-tool-progress"]
    assert progress == [
        {
            "type": "data-tool-progress",
            "data": {
                "toolCallId": "call-1",
                "progress": 12,
                "total": 44,
                "message": "Read 12 of 44 parts",
            },
            "transient": True,
        }
    ]
