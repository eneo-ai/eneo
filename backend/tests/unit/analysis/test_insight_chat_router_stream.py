"""An insights turn streams as the chat API's version 3 UI Message Stream,
through the chat's own encoder (the HTTP round trip runs in
``tests/integration/analysis/test_insight_chat_router.py``)."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from starlette.requests import Request

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelPublic,
    ResponseType,
    ToolCallMetadata,
)
from eneo.analysis import insight_chat_router
from eneo.analysis.insight_conversation_service import InsightTurn
from eneo.sessions.session import SessionInDB


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/analysis/conversation-insights/chat/",
            "headers": [],
            "server": ("backend", 8123),
            "scheme": "http",
            "query_string": b"",
        }
    )


def _public_model(model_id: Any) -> CompletionModelPublic:
    return CompletionModelPublic(
        id=model_id,
        name="tools-model",
        nickname="Tools",
        max_input_tokens=10_000,
        max_output_tokens=4_000,
        is_deprecated=False,
        vision=False,
        reasoning=False,
    )


async def _answer():
    call = ToolCallMetadata(
        server_name="insights",
        tool_name="top_questions",
        title="Top questions",
        arguments={"n": 5},
        tool_call_id="call-1",
        result="Top 5 exact-text question groups ...",
        result_status="succeeded",
        is_internal=True,
        is_bundled=False,
    )
    yield Completion(response_type=ResponseType.TOOL_CALL, tool_calls_metadata=[call])
    yield Completion(response_type=ResponseType.TEXT, text="Mest om bygglov.")


async def _events(response: Any) -> list[str]:
    payloads: list[str] = []
    async for event in response.body_iterator:
        encoded = event.encode() if hasattr(event, "encode") else event
        text = encoded.decode() if isinstance(encoded, bytes) else str(encoded)
        assert text.startswith("data: ")
        payloads.append(text.removeprefix("data: ").strip())
    return payloads


@pytest.mark.parametrize("show_pricing", [True, False])
async def test_a_turn_streams_the_version_3_ui_message_stream(
    monkeypatch: pytest.MonkeyPatch, show_pricing: bool
):
    model = SimpleNamespace(id=uuid4())
    priced: list[bool] = []

    def from_domain(domain: Any, *, show_pricing: bool) -> CompletionModelPublic:
        assert domain is model
        priced.append(show_pricing)
        return _public_model(domain.id)

    monkeypatch.setattr(
        insight_chat_router.CompletionModelPublic, "from_domain", from_domain
    )
    session = SessionInDB(id=uuid4(), name="Vilka frågor?", user_id=uuid4())
    question_id = uuid4()
    turn = InsightTurn(
        session=session,
        question="Vilka frågor?",
        question_id=question_id,
        created_at=datetime.now(timezone.utc),
        completion_model=model,  # pyright: ignore[reportArgumentType]
        answer=_answer(),
        target_name="Bygg",
        space_id=uuid4(),
    )

    response = insight_chat_router._stream(
        turn, http_request=_request(), show_pricing=show_pricing
    )

    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
    assert response.headers["content-type"].startswith("text/event-stream")
    payloads = await _events(response)
    assert payloads[-1] == "[DONE]"
    events = [json.loads(payload) for payload in payloads[:-1]]
    assert [event["type"] for event in events] == [
        "start",
        "data-session",
        "tool-input-available",
        "tool-output-available",
        "text-start",
        "text-delta",
        "text-end",
        "finish",
    ]
    # The live answer gets the id its saved turn will have.
    assert events[0]["messageId"] == str(question_id)
    data = events[1]["data"]
    assert data["session_id"] == str(session.id)
    assert data["completion_model"]["id"] == str(model.id)
    assert data["files"] == [] and data["mcp_tool_references"] == []
    assert data["answering_assistant"] is None
    assert priced == [show_pricing]
    for tool_part in events[2:4]:
        eneo = tool_part["providerMetadata"]["eneo"]
        assert eneo["server_name"] == "insights"
        assert eneo["is_internal"] is True
    # The call's status is streamed, never its result.
    assert events[3]["output"] == {"status": "succeeded"}
    assert "Top 5 exact-text" not in json.dumps(events)
