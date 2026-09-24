"""What a widget visitor receives, checked on the serialised payloads."""

import json
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    McpToolReference,
    ResponseType,
    TokenUsage,
    ToolCallMetadata,
)
from eneo.assistants.api import assistant_protocol
from eneo.assistants.api.assistant_models import AssistantResponse
from eneo.info_blobs.info_blob import InfoBlobInDB, InfoBlobInDBWithScore
from eneo.questions.question import (
    McpToolReferencePublic,
    Question,
    ToolAssistant,
    ToolCallInfo,
    UseTools,
)
from eneo.sessions.session import SessionInDB
from eneo.sessions.session_protocol import to_session_public
from eneo.skills.domain.skill import SkillExecutionReference
from eneo.widgets.application.visitor_view import VisitorView
from eneo.widgets.domain.widget import Widget
from tests.fixtures import TEST_MODEL_CHATGPT

NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)
INTERNAL_MODEL = TEST_MODEL_CHATGPT.model_copy(
    update={
        "base_url": "https://llm.internal.kommun.se/v1",
        "litellm_model_name": "azure/gpt-internal",
        "deployment_name": "gpt-internal-prod",
    }
)
SECRET_CONTENT = "Ärende 2026-123: personuppgifter"


def _widget(**overrides) -> Widget:
    widget = Widget.create(
        tenant_id=uuid4(), space_id=uuid4(), target_id=uuid4(), name="w"
    )
    return widget.model_copy(update={"id": uuid4(), **overrides})


def _blob(**overrides) -> InfoBlobInDBWithScore:
    return InfoBlobInDBWithScore(
        id=uuid4(),
        title="Intern rutin för bibliotek",
        url="https://intranet.kommun.se/rutin",
        embedding_model_id=uuid4(),
        user_id=uuid4(),
        tenant_id=uuid4(),
        size=10,
        source_id=uuid4(),
        version_state="active",
        text="Öppettider",
        original_available=True,
        score=0.9,
        **overrides,
    )


def _mcp_ref() -> McpToolReference:
    return McpToolReference(
        id=uuid4(),
        tool_call_id="call_1",
        mcp_tool_name="casefiles__search_casefiles",
        uri="https://casefiles.kommun.se/2026-123",
        mime_type="text/plain",
        content=SECRET_CONTENT,
        meta={"title": "Ärende 2026-123", "sourceType": "web", "internal_id": 42},
        order=0,
    )


def _tool_call() -> ToolCallMetadata:
    return ToolCallMetadata(
        server_name="casefiles",
        tool_name="search_casefiles",
        title="Search case files",
        arguments={"query": "bibliotek"},
        tool_call_id="call_1",
        result_status="success",
        result=SECRET_CONTENT,
        mcp_tool_name="casefiles__search_casefiles",
        meta={"gen_ai.request.model": "internal-model"},
    )


def _tool_chunk() -> Completion:
    return Completion(
        text="",
        response_type=ResponseType.TOOL_CALL,
        tool_calls_metadata=[_tool_call()],
        mcp_tool_references=[_mcp_ref()],
    )


def _sse(chunk: Completion) -> dict:
    return json.loads(assistant_protocol.to_sse_response(chunk, uuid4()).data)


# --- first chunk ------------------------------------------------------------


@pytest.mark.parametrize("show_sources", [True, False])
def test_first_chunk_names_no_model_assistant_or_retrieved_document(show_sources):
    response = AssistantResponse(
        session=SessionInDB(id=uuid4(), name="s"),
        question="Öppettider?",
        question_id=uuid4(),
        files=[],
        answer="",
        info_blobs=[_blob()],
        completion_model=INTERNAL_MODEL,
        tools=UseTools(assistants=[ToolAssistant(id=uuid4(), handle="Intern")]),
    )

    visible = VisitorView(_widget(show_sources=show_sources)).response(response)
    first = assistant_protocol.to_ask_conversation_response(
        question=visible.question,
        files=visible.files,
        session=visible.session,
        answer="",
        info_blobs=visible.info_blobs,
        tools=visible.tools,
        completion_model=visible.completion_model,
        question_id=visible.question_id,
    ).model_dump(mode="json")

    assert first["completion_model"] is None
    assert first["references"] == []
    assert first["tools"] == {"assistants": []}
    assert "intranet.kommun.se" not in json.dumps(first)
    # The original response is not touched: persistence still reads it.
    assert response.completion_model is not None
    assert response.info_blobs


# --- stream -------------------------------------------------------------------


def _text(text: str) -> Completion:
    return Completion(text=text, response_type=ResponseType.TEXT)


def _cite(ref: McpToolReference) -> str:
    return f'<inref id="{str(ref.id)[:8]}"/>'


def _stream(view: VisitorView, *chunks: Completion) -> list[dict]:
    return [_sse(event) for chunk in chunks for event in view.events(chunk)]


def test_reasoning_approval_and_token_usage_never_reach_a_visitor():
    view = VisitorView(_widget())
    for response_type in (
        ResponseType.REASONING,
        ResponseType.TOOL_APPROVAL_REQUIRED,
        ResponseType.TOOL_APPROVAL_TIMEOUT,
        ResponseType.TOKEN_USAGE,
    ):
        chunk = Completion(
            reasoning_content="The system prompt says…",
            response_type=response_type,
            tool_calls_metadata=[_tool_call()],
            approval_id="a",
            usage=TokenUsage(prompt_tokens=900, completion_tokens=10),
            skill_context_tokens=400,
        )
        assert view.events(chunk) == []


def test_hidden_sources_strip_cited_documents_from_text():
    chunk = Completion(
        text="Hej", response_type=ResponseType.TEXT, reference_chunks=[_blob()]
    )

    [hidden] = VisitorView(_widget(show_sources=False)).events(chunk)
    [shown] = VisitorView(_widget(show_sources=True)).events(chunk)

    assert _sse(hidden)["references"] == []
    assert _sse(shown)["references"][0]["metadata"]["title"] == (
        "Intern rutin för bibliotek"
    )


def test_tool_event_keeps_the_call_and_the_argument_the_widget_shows():
    original = _tool_chunk()
    original.tool_calls_metadata[0].arguments = {
        "limit": 10,
        "query": "bibliotek",
        "email": "anna@kommun.se",
    }

    [visible] = VisitorView(_widget()).events(original)

    event = _sse(visible)
    assert event["tools"] == [
        {
            "server_name": "casefiles",
            "tool_name": "search_casefiles",
            "title": "Search case files",
            "arguments": {"query": "bibliotek"},
            "tool_call_id": "call_1",
            "approved": None,
            "result_status": "success",
            "result": None,
            "mcp_tool_name": "casefiles__search_casefiles",
            "purpose": None,
            "meta": None,
            "generated_file_ids": None,
        }
    ]
    assert event["mcp_tool_references"] == []
    assert SECRET_CONTENT not in json.dumps(event)
    assert "anna@kommun.se" not in json.dumps(event)
    # The stream's own objects keep their content: the answer's references
    # are persisted from them after the stream ends.
    assert original.mcp_tool_references is not None
    assert original.mcp_tool_references[0].content == SECRET_CONTENT
    assert original.tool_calls_metadata is not None
    assert original.tool_calls_metadata[0].result == SECRET_CONTENT
    assert "email" in original.tool_calls_metadata[0].arguments


@pytest.mark.parametrize(
    ("arguments", "shown"),
    [
        ({"q": "öppettider", "id": "7"}, {"q": "öppettider"}),
        (
            {"query": " ", "timezone": "Europe/Stockholm"},
            {"timezone": "Europe/Stockholm"},
        ),
        ({"limit": 5, "filter": "open"}, {"filter": "open"}),
        ({"limit": 5}, {}),
        ({}, {}),
        (None, None),
    ],
)
def test_only_one_argument_leaves_the_server(arguments, shown):
    call = replace(_tool_call(), arguments=arguments)
    chunk = Completion(
        text="", response_type=ResponseType.TOOL_CALL, tool_calls_metadata=[call]
    )

    [event] = _stream(VisitorView(_widget()), chunk)

    assert event["tools"][0]["arguments"] == shown


def test_a_tool_resource_reaches_the_visitor_only_once_the_answer_cites_it():
    cited, uncited = _mcp_ref(), _mcp_ref()
    uncited.uri = "https://casefiles.kommun.se/2026-999"
    uncited.meta = {"title": "Ärende 2026-999: Namn Namnsson"}
    tool = replace(_tool_chunk(), mcp_tool_references=[cited, uncited])
    view = VisitorView(_widget())

    events = _stream(view, tool, _text("Enligt ärendet "), _text(_cite(cited)))

    assert [event.get("mcp_tool_references") for event in events[:2]] == [[], None]
    # The resource arrives just before the text that cites it.
    [ref] = events[2]["mcp_tool_references"]
    assert events[2]["tools"] == []
    assert ref["uri"] == "https://casefiles.kommun.se/2026-123"
    assert ref["meta"] == {"title": "Ärende 2026-123", "sourceType": "web"}
    assert ref["content"] is None
    assert ref["tool_call_id"] == "call_1"
    assert events[3]["answer"] == _cite(cited)
    payload = json.dumps(events)
    assert "2026-999" not in payload and "Namnsson" not in payload
    # A second citation of the same resource sends nothing new.
    assert [event["answer"] for event in _stream(view, _text(_cite(cited)))] == [
        _cite(cited)
    ]


def test_a_citation_split_across_text_chunks_still_releases_its_resource():
    ref = _mcp_ref()
    marker = _cite(ref)
    view = VisitorView(_widget())

    events = _stream(view, _tool_chunk_with(ref), _text(marker[:9]), _text(marker[9:]))

    assert [len(event.get("mcp_tool_references") or []) for event in events] == [
        0,
        0,
        1,
        0,
    ]
    assert events[2]["mcp_tool_references"][0]["uri"] == ref.uri


def test_tool_images_are_not_held_back():
    image = replace(_mcp_ref(), mime_type="image/png", uri="https://img/x.png")

    [event] = _stream(VisitorView(_widget()), _tool_chunk_with(image))

    assert [ref["uri"] for ref in event["mcp_tool_references"]] == ["https://img/x.png"]


def test_hidden_tool_activity_keeps_cited_sources_without_naming_the_tool():
    ref = _mcp_ref()
    view = VisitorView(_widget(show_tool_activity=False))

    events = _stream(view, _tool_chunk_with(ref), _text(_cite(ref)))

    [source_event, text_event] = events
    assert source_event["tools"] == []
    [shown] = source_event["mcp_tool_references"]
    assert shown["uri"] == "https://casefiles.kommun.se/2026-123"
    assert shown["meta"] == {"title": "Ärende 2026-123", "sourceType": "web"}
    assert shown["tool_call_id"] is None and shown["mcp_tool_name"] is None
    assert "casefiles__" not in json.dumps(events)
    assert "search_casefiles" not in json.dumps(events)
    assert text_event["answer"] == _cite(ref)


def test_hidden_sources_keep_tool_calls_but_no_tool_references():
    ref = _mcp_ref()
    view = VisitorView(_widget(show_sources=False))

    events = _stream(view, _tool_chunk_with(ref), _text(_cite(ref)))

    assert [tool["tool_name"] for tool in events[0]["tools"]] == ["search_casefiles"]
    assert [event.get("mcp_tool_references") for event in events] == [[], None]
    assert ref.uri not in json.dumps(events)


def test_tool_event_is_dropped_when_nothing_in_it_may_be_shown():
    view = VisitorView(_widget(show_sources=False, show_tool_activity=False))
    assert view.events(_tool_chunk()) == []

    only_calls = Completion(
        text="",
        response_type=ResponseType.TOOL_CALL,
        tool_calls_metadata=[_tool_call()],
    )
    assert VisitorView(_widget(show_tool_activity=False)).events(only_calls) == []


def _tool_chunk_with(ref: McpToolReference) -> Completion:
    return replace(_tool_chunk(), mcp_tool_references=[ref])


# --- restore and feedback ---------------------------------------------------


def _stored_session() -> SessionInDB:
    blob = _blob()
    question = Question(
        id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
        question="Öppettider?",
        answer="Vi har öppet 10–18.",
        num_tokens_question=10,
        num_tokens_answer=5,
        context_prompt_tokens=900,
        context_completion_tokens=5,
        skill_context_tokens=400,
        tenant_id=uuid4(),
        session_id=uuid4(),
        completion_model=INTERNAL_MODEL,
        completion_model_id=INTERNAL_MODEL.id,
        assistant_id=uuid4(),
        reasoning="Instruktionen säger att jag inte ska nämna…",
        skill_provenance=[
            SkillExecutionReference(
                skill_id=uuid4(),
                skill_revision_id=uuid4(),
                revision_number=1,
                content_digest="d",
                position=0,
            )
        ],
        info_blobs=[InfoBlobInDB(**blob.model_dump(exclude={"score"}))],
        mcp_tool_references=[
            McpToolReferencePublic(
                id=uuid4(),
                uri="https://casefiles.kommun.se/2026-123",
                content=SECRET_CONTENT,
                meta={"title": "Ärende 2026-123", "internal_id": 42},
                tool_call_id="call_1",
                mcp_tool_name="casefiles__search_casefiles",
            )
        ],
        tool_calls=[
            ToolCallInfo(
                server_name="casefiles",
                tool_name="search_casefiles",
                arguments={"query": "bibliotek", "email": "anna@kommun.se"},
                tool_call_id="call_1",
                result=SECRET_CONTENT,
                meta={"gen_ai.request.model": "internal-model"},
                generated_file_ids=[uuid4()],
            )
        ],
    )
    question.assistant_name = "Intern assistent"
    return SessionInDB(id=uuid4(), name="s", questions=[question])


def _restored(**widget_overrides) -> dict:
    session = VisitorView(_widget(**widget_overrides)).session(_stored_session())
    return to_session_public(session).model_dump(mode="json")


@pytest.mark.parametrize(
    "overrides",
    [{}, {"show_sources": False}, {"show_tool_activity": False}],
)
def test_restored_messages_never_carry_internal_data(overrides):
    [message] = _restored(**overrides)["messages"]
    payload = json.dumps(message)

    assert message["completion_model"] is None
    assert message["reasoning"] is None
    assert message["skill_provenance"] is None
    assert message["tools"] == {"assistants": []}
    assert SECRET_CONTENT not in payload
    for leaked in (
        "llm.internal",
        "gpt-internal",
        "Intern assistent",
        "internal_id",
        "anna@kommun.se",
    ):
        assert leaked not in payload
    assert message["skill_context_tokens"] is None
    assert message["context_prompt_tokens"] is None
    assert message["context_completion_tokens"] is None
    assert (message["num_tokens_question"], message["num_tokens_answer"]) == (0, 0)
    assert message["answer"] == "Vi har öppet 10–18."


def test_restored_session_with_everything_shown():
    [message] = _restored()["messages"]

    assert message["references"][0]["metadata"]["title"] == (
        "Intern rutin för bibliotek"
    )
    [ref] = message["mcp_tool_references"]
    assert ref["meta"] == {"title": "Ärende 2026-123"}
    assert ref["tool_call_id"] == "call_1"
    [call] = message["tool_calls"]
    assert call["arguments"] == {"query": "bibliotek"}
    assert call["result"] is None and call["meta"] is None
    assert call["generated_file_ids"] is None


def test_restored_session_with_sources_hidden():
    [message] = _restored(show_sources=False)["messages"]

    assert message["references"] == []
    assert message["mcp_tool_references"] == []
    assert [call["tool_name"] for call in message["tool_calls"]] == ["search_casefiles"]


def test_restored_session_with_tool_activity_hidden():
    [message] = _restored(show_tool_activity=False)["messages"]

    assert message["tool_calls"] == []
    [ref] = message["mcp_tool_references"]
    assert ref["uri"] == "https://casefiles.kommun.se/2026-123"
    assert ref["tool_call_id"] is None and ref["mcp_tool_name"] is None
    assert message["references"]
