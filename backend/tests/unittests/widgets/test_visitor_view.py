"""What a widget visitor receives, checked on the serialised payloads."""

import json
from dataclasses import replace
from datetime import datetime, timezone
from time import perf_counter
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
from eneo.assistants.reference_tags import strip_inline_references
from eneo.completion_models.domain.skill_activation import SKILL_ACTIVATION_TOOL_NAME
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
    original.tool_calls_metadata[0].structured_content = {"rows": [SECRET_CONTENT]}
    original.tool_calls_metadata[0].app_view = {"view_id": "v1", "ui": {}}

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
            "mcp_tool_name": None,
            "purpose": None,
            "is_internal": None,
            "is_bundled": None,
            "meta": None,
            "generated_file_ids": None,
            "structured_content": None,
            "app_view": None,
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


@pytest.mark.parametrize("show_tool_activity", [True, False])
@pytest.mark.parametrize("show_sources", [True, False])
@pytest.mark.parametrize("fragmented", [True, False])
def test_tool_argument_deltas_never_reach_visitor_sse(
    show_tool_activity, show_sources, fragmented
):
    arguments = {"query": "bibliotek", "private": {"note": SECRET_CONTENT}}
    raw = json.dumps(arguments, ensure_ascii=True)
    pieces = [raw[:20], raw[20:45], raw[45:]] if fragmented else [raw]
    call = replace(_tool_call(), arguments=arguments)
    chunks = [
        Completion(
            response_type=ResponseType.TOOL_CALL,
            tool_calls_metadata=[
                replace(call, arguments=None, result_status="pending", result=None)
            ],
        ),
        *[
            Completion(
                response_type=ResponseType.TOOL_CALL_DELTA,
                tool_call_id="call_1",
                arguments_delta=piece,
            )
            for piece in pieces
        ],
        Completion(response_type=ResponseType.TOOL_CALL, tool_calls_metadata=[call]),
        Completion(response_type=ResponseType.TEXT, text="Hej"),
    ]
    view = VisitorView(
        _widget(show_tool_activity=show_tool_activity, show_sources=show_sources)
    )
    events = [
        assistant_protocol.to_sse_response(visible, uuid4())
        for chunk in chunks
        for visible in view.events(chunk)
    ]

    assert [event.event for event in events] == (
        ["tool_call", "tool_call", "text"] if show_tool_activity else ["text"]
    )
    payloads = [json.loads(event.data) for event in events]
    assert all("arguments_delta" not in payload for payload in payloads)
    assert SECRET_CONTENT not in json.dumps(payloads, ensure_ascii=False)
    assert payloads[-1]["answer"] == "Hej"
    if show_tool_activity:
        assert payloads[0]["tools"][0]["result_status"] == "pending"
        assert payloads[1]["tools"][0]["arguments"] == {"query": "bibliotek"}


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


def _knowledge_passage(**meta) -> McpToolReference:
    document = uuid4()
    return McpToolReference(
        id=uuid4(),
        tool_call_id="call_k",
        mcp_tool_name="knowledge__search_knowledge",
        uri=f"eneo://info-blob/{document}#chunk-3",
        mime_type="text/plain",
        content=SECRET_CONTENT,
        meta={
            "title": "Avgifter för bygglov",
            "info_blob_id": str(document),
            "url": "https://www.kommun.se/avgifter",
            "score": 0.91,
            "context_for_chunk": 2,
            **meta,
        },
        order=0,
    )


def test_a_cited_knowledge_passage_names_its_document_but_not_its_text():
    passage = _knowledge_passage()
    view = VisitorView(_widget())

    events = _stream(view, _tool_chunk_with(passage), _text(_cite(passage)))

    [ref] = events[1]["mcp_tool_references"]
    assert ref["content"] is None
    assert ref["meta"] == {
        "title": "Avgifter för bygglov",
        "info_blob_id": passage.meta["info_blob_id"],
        "url": "https://www.kommun.se/avgifter",
    }
    assert SECRET_CONTENT not in json.dumps(events)


def test_only_a_knowledge_passage_keeps_a_document_id_and_address():
    ref = replace(
        _mcp_ref(),
        meta={"title": "Ärende", "info_blob_id": "x", "url": "https://tracker.example"},
    )
    view = VisitorView(_widget())

    events = _stream(view, _tool_chunk_with(ref), _text(_cite(ref)))

    assert events[1]["mcp_tool_references"][0]["meta"] == {"title": "Ärende"}


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
                app_view={
                    "view_id": "private-view",
                    "mcp_server_id": "private-server",
                    "ui": {},
                },
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
    assert call["app_view"] is None
    assert call["generated_file_ids"] is None


def test_a_restored_knowledge_passage_names_its_document_but_not_its_text():
    passage = _knowledge_passage()
    stored = _stored_session()
    question = stored.questions[0].model_copy(
        update={
            "mcp_tool_references": [
                McpToolReferencePublic(
                    id=passage.id,
                    uri=passage.uri,
                    content=passage.content,
                    meta=passage.meta,
                    tool_call_id=passage.tool_call_id,
                    mcp_tool_name=passage.mcp_tool_name,
                )
            ]
        }
    )
    session = VisitorView(_widget()).session(
        stored.model_copy(update={"questions": [question]})
    )

    [message] = to_session_public(session).model_dump(mode="json")["messages"]
    [ref] = message["mcp_tool_references"]
    assert ref["content"] is None
    assert set(ref["meta"]) == {"title", "info_blob_id", "url"}


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


# --- hidden sources ---------------------------------------------------------


def _knowledge_call(**overrides) -> ToolCallMetadata:
    return replace(
        _tool_call(),
        **{
            "server_name": "knowledge",
            "tool_name": "search_knowledge",
            "is_internal": True,
            "arguments": {"query": "bygglov", "within": "Interna rutiner"},
            **overrides,
        },
    )


@pytest.mark.parametrize(
    ("call", "shown"),
    [
        (_knowledge_call(), {"query": "bygglov"}),
        (_knowledge_call(arguments={"query": " ", "within": "Interna"}), {}),
        (
            _knowledge_call(
                tool_name="read_source",
                arguments={"document_id": "Intern rutin", "offset": 0},
            ),
            {},
        ),
        (
            _knowledge_call(
                tool_name="describe_source", arguments={"source_id": "Intern"}
            ),
            {},
        ),
        # A row stored before the flag existed counts as Eneo's own.
        (_knowledge_call(is_internal=None), {"query": "bygglov"}),
        # An external server may be named "knowledge" too.
        (
            _knowledge_call(
                is_internal=False, arguments={"document_id": "Offentlig sida"}
            ),
            {"document_id": "Offentlig sida"},
        ),
    ],
)
def test_hidden_sources_show_a_knowledge_call_only_its_search_terms(call, shown):
    widget = _widget(show_sources=False)
    chunk = replace(_tool_chunk(), tool_calls_metadata=[call])

    [visible] = VisitorView(widget).events(chunk)
    assert _sse(visible)["tools"][0]["arguments"] == shown

    session = _stored_session()
    session.questions[0].tool_calls = [
        ToolCallInfo(
            server_name=call.server_name,
            tool_name=call.tool_name,
            arguments=call.arguments,
            is_internal=call.is_internal,
        )
    ]
    payload = to_session_public(VisitorView(widget).session(session))
    [message] = payload.model_dump(mode="json")["messages"]
    assert message["tool_calls"][0]["arguments"] == shown


def test_shown_sources_keep_the_argument_a_knowledge_call_displays():
    call = _knowledge_call(
        tool_name="read_source", arguments={"document_id": "Rutin", "offset": 0}
    )
    chunk = replace(_tool_chunk(), tool_calls_metadata=[call])

    [visible] = VisitorView(_widget()).events(chunk)

    assert _sse(visible)["tools"][0]["arguments"] == {"document_id": "Rutin"}


CITED_ANSWER = (
    'Vi har öppet 9–17 <inref id="a5477f85"/>.\n\n'
    'Avgiften är 5 < 10 kr<inref id="b3291cc0"/><inref id="c0ffee00"></inref>.'
)
UNCITED_ANSWER = "Vi har öppet 9–17.\n\nAvgiften är 5 < 10 kr."


def _visible_text(view: VisitorView, pieces: list[str]) -> str:
    events = [
        event
        for piece in pieces
        for event in view.events(
            Completion(text=piece, response_type=ResponseType.TEXT)
        )
    ]
    return "".join(event.text or "" for event in [*events, *view.finish()])


@pytest.mark.parametrize("cut", range(len(CITED_ANSWER) + 1))
def test_hidden_sources_strip_citations_wherever_a_chunk_ends(cut):
    view = VisitorView(_widget(show_sources=False))

    text = _visible_text(view, [CITED_ANSWER[:cut], CITED_ANSWER[cut:]])

    assert text == UNCITED_ANSWER


def test_hidden_sources_strip_citations_streamed_one_character_at_a_time():
    view = VisitorView(_widget(show_sources=False))

    assert _visible_text(view, list(CITED_ANSWER)) == UNCITED_ANSWER


def test_hidden_sources_drop_a_citation_the_answer_was_cut_off_in():
    view = VisitorView(_widget(show_sources=False))

    assert _visible_text(view, ["Öppet 9–17 ", '<inref id="a5477']) == "Öppet 9–17"


def test_held_text_comes_before_the_error_that_ends_the_answer():
    view = VisitorView(_widget(show_sources=False))
    assert (
        view.events(Completion(text="Öppet ", response_type=ResponseType.TEXT))[0].text
        == "Öppet"
    )

    held, failure = view.events(
        Completion(text="", error="x", response_type=ResponseType.ERROR, stop=True)
    )

    assert (held.response_type, held.text) == (ResponseType.TEXT, " ")
    assert failure.response_type == ResponseType.ERROR
    assert view.finish() == []


def test_a_citation_split_around_a_tool_event_stays_hidden():
    view = VisitorView(_widget(show_sources=False))

    first = view.events(_text('Öppet <inref id="1234'))
    tool = view.events(_tool_chunk())
    second = view.events(_text('5678"/>.'))

    assert [event.response_type for event in tool] == [ResponseType.TOOL_CALL]
    text = "".join(e.text or "" for e in [*first, *second, *view.finish()])
    assert text == "Öppet."


@pytest.mark.parametrize(
    "answer",
    [
        "Svar <inref" + " " * 40 + 'id="12345678"/>.',
        'Svar <inref id="00000000-0000-4000-8000-000000000000" />.',
        'Svar <inref\n id="a5477f85"\n/>.',
        "Ett <inreference> och <b>fet</b> text, 1 < 2 > 0.",
        "Slutar på <inre",
        "Slutar på <",
        'Bruten <inref id="1234',
    ],
)
def test_the_stream_gives_what_a_restore_gives_wherever_a_chunk_ends(answer):
    expected = strip_inline_references(answer)
    assert "<inref " not in expected
    for cut in range(len(answer) + 1):
        view = VisitorView(_widget(show_sources=False))
        assert _visible_text(view, [answer[:cut], answer[cut:]]) == expected


def test_a_long_run_of_spaces_costs_a_stream_no_more_than_a_scan_per_chunk():
    view = VisitorView(_widget(show_sources=False))
    pieces = ["Svar <inref", *[" " * 32] * 500, 'id="12345678"/>.']

    started = perf_counter()
    text = _visible_text(view, pieces)

    assert text == "Svar."
    assert perf_counter() - started < 2


def test_a_held_end_of_text_reaches_the_visitor_when_the_answer_ends():
    view = VisitorView(_widget(show_sources=False))

    assert _visible_text(view, ["5 <"]) == "5 <"


def test_shown_sources_keep_citations_in_the_text():
    view = VisitorView(_widget())

    assert _visible_text(view, [CITED_ANSWER]) == CITED_ANSWER


def test_hidden_sources_strip_citations_on_restore():
    session = _stored_session()
    session.questions[0].answer = CITED_ANSWER

    hidden = to_session_public(
        VisitorView(_widget(show_sources=False)).session(session)
    )
    shown = to_session_public(VisitorView(_widget()).session(session))

    assert hidden.model_dump(mode="json")["messages"][0]["answer"] == UNCITED_ANSWER
    assert shown.model_dump(mode="json")["messages"][0]["answer"] == CITED_ANSWER


# --- errors -----------------------------------------------------------------


def test_a_stream_error_says_nothing_about_the_model_or_the_provider():
    failure = Completion(
        text="",
        error="The AI provider does not offer the configured model.",
        error_code=404,
        error_reason="provider_model_not_found",
        response_type=ResponseType.ERROR,
        stop=True,
    )

    [visible] = VisitorView(_widget()).events(failure)

    event = _sse(visible)
    assert event["code"] == "answer_unavailable"
    assert event["error_code"] == 503
    assert "provider" not in json.dumps(event).lower()
    assert failure.error_reason == "provider_model_not_found"


# --- Skills -----------------------------------------------------------------


def _skill_activation() -> ToolCallMetadata:
    return ToolCallMetadata(
        server_name="skills",
        tool_name="rutin-for-arenden",
        title="Rutin för ärenden",
        arguments={"skill_key": "rutin-for-arenden", "reason": "ärende"},
        tool_call_id="skill-call",
        approved=True,
        result_status="completed",
        result='{"activated": true}',
        mcp_tool_name=SKILL_ACTIVATION_TOOL_NAME,
        is_internal=True,
    )


def test_a_skill_activation_never_reaches_the_stream():
    only_skill = Completion(
        text="",
        response_type=ResponseType.TOOL_CALL,
        tool_calls_metadata=[_skill_activation()],
    )
    assert VisitorView(_widget()).events(only_skill) == []

    both = replace(only_skill, tool_calls_metadata=[_skill_activation(), _tool_call()])
    [visible] = VisitorView(_widget()).events(both)
    event = json.dumps(_sse(visible))
    assert [tool["tool_name"] for tool in _sse(visible)["tools"]] == [
        "search_casefiles"
    ]
    assert "rutin-for-arenden" not in event
    assert "Rutin för ärenden" not in event


def test_a_skill_activation_never_reaches_a_restored_session():
    session = _stored_session()
    question = session.questions[0]
    question.tool_calls = [
        ToolCallInfo(
            server_name="skills",
            tool_name="rutin-for-arenden",
            title="Rutin för ärenden",
            arguments={"skill_key": "rutin-for-arenden"},
            tool_call_id="skill-call",
            mcp_tool_name=SKILL_ACTIVATION_TOOL_NAME,
            is_internal=True,
        ),
        *(question.tool_calls or []),
    ]

    payload = to_session_public(VisitorView(_widget()).session(session))

    [message] = payload.model_dump(mode="json")["messages"]
    assert [call["tool_name"] for call in message["tool_calls"]] == ["search_casefiles"]
    assert "rutin-for-arenden" not in json.dumps(message)
