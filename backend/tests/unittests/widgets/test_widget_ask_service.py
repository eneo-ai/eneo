import asyncio
import json
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import anyio
import pytest
from starlette.types import Message

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    McpToolReference,
    ResponseType,
    ToolCallMetadata,
)
from eneo.assistants.api import assistant_protocol
from eneo.assistants.api.assistant_models import AssistantResponse
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.info_blobs.info_blob import InfoBlobInDB, InfoBlobInDBWithScore
from eneo.main import stream_lifecycle
from eneo.main.exceptions import (
    BadRequestException,
    ModelNotAvailableException,
    NotFoundException,
    OpenAIException,
    ProviderInactiveException,
    ProviderRejectedRequestException,
    UnauthorizedException,
)
from eneo.questions.question import (
    McpToolReferencePublic,
    Question,
    ToolAssistant,
    ToolCallInfo,
    UseTools,
)
from eneo.sessions.session import SessionFeedback, SessionInDB
from eneo.sessions.session_protocol import to_session_public
from eneo.widgets.application import widget_ask_service as module
from eneo.widgets.application.widget_ask_service import (
    SessionNotOwnedError,
    WidgetAskService,
)
from eneo.widgets.application.widget_limits import BudgetReservation
from eneo.widgets.domain.exceptions import (
    WidgetAnswerUnavailableError,
    WidgetBudgetExhaustedError,
    WidgetPublicError,
    WidgetRateLimitedError,
)
from eneo.widgets.domain.visitor import VisitorClaims, WidgetPrincipal
from eneo.widgets.domain.widget import Widget, WidgetLimits, WidgetPrivacy
from tests.fixtures import TEST_MODEL_CHATGPT

INTERNAL_MODEL = TEST_MODEL_CHATGPT.model_copy(
    update={
        "base_url": "https://llm.internal.kommun.se/v1",
        "litellm_model_name": "azure/gpt-internal",
    }
)
RESOURCE_CONTENT = "Ärende 2026-123: personuppgifter"


def _widget(**overrides) -> Widget:
    widget = Widget.create(
        tenant_id=uuid4(), space_id=uuid4(), target_id=uuid4(), name="w"
    )
    return widget.model_copy(update={"id": uuid4(), **overrides})


def _principal(widget: Widget, *, preview: bool = False) -> WidgetPrincipal:
    claims = MagicMock(spec=VisitorClaims)
    claims.preview = preview
    return WidgetPrincipal(widget=widget, visitor_id=uuid4(), claims=claims)


async def _chunks():
    for text in ("Hej", " där"):
        yield Completion(text=text, response_type=ResponseType.TEXT)


def _blob() -> InfoBlobInDBWithScore:
    return InfoBlobInDBWithScore(
        id=uuid4(),
        title="Intern rutin",
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
    )


def _ask_result(session, answer) -> AssistantResponse:
    """What AssistantService.ask returns for a stream: every retrieved
    document and the full model record."""
    return AssistantResponse.model_construct(
        session=session,
        question="q",
        question_id=uuid4(),
        files=[],
        answer=answer,
        info_blobs=[_blob()],
        completion_model=INTERNAL_MODEL,
        tools=UseTools(assistants=[ToolAssistant(id=uuid4(), handle="Intern")]),
        mcp_tool_references=[],
    )


def _stored_question() -> Question:
    question = Question(
        id=uuid4(),
        created_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
        question="Öppettider?",
        answer="10–18.",
        num_tokens_question=10,
        num_tokens_answer=5,
        tenant_id=uuid4(),
        session_id=uuid4(),
        completion_model=INTERNAL_MODEL,
        assistant_id=uuid4(),
        reasoning="Instruktionen säger…",
        info_blobs=[InfoBlobInDB(**_blob().model_dump(exclude={"score"}))],
        mcp_tool_references=[
            McpToolReferencePublic(
                id=uuid4(),
                uri="https://casefiles.kommun.se/2026-123",
                content=RESOURCE_CONTENT,
                meta={"title": "Ärende 2026-123"},
                tool_call_id="call_1",
                mcp_tool_name="casefiles__search",
            )
        ],
        tool_calls=[
            ToolCallInfo(
                server_name="casefiles",
                tool_name="search",
                arguments={"query": "bibliotek"},
                tool_call_id="call_1",
                result=RESOURCE_CONTENT,
                meta={"gen_ai.request.model": "internal"},
            )
        ],
    )
    question.assistant_name = "Intern assistent"
    return question


def _stored_session(questions: int = 1) -> SessionInDB:
    return SessionInDB(
        id=uuid4(), name="s", questions=[_stored_question() for _ in range(questions)]
    )


def _service(*, ask_result=None, session_questions=0, tokens=(120, 80)):
    assistant_service = MagicMock()
    session_obj = _stored_session(session_questions)
    assistant_service.ask = AsyncMock(
        return_value=ask_result or _ask_result(session_obj, _chunks())
    )
    session_service = MagicMock()
    session_service.get_session_by_uuid = AsyncMock(return_value=session_obj)
    session_service.leave_feedback = AsyncMock(return_value=session_obj)
    limiter = MagicMock()
    limiter.check_message = AsyncMock()
    limiter.hold_turn = AsyncMock()
    limiter.release_turn = AsyncMock()
    budget = MagicMock()
    budget.reserve = AsyncMock(
        return_value=BudgetReservation(
            id=uuid4(), widget_id=uuid4(), day=date.today(), reserved_tokens=8_000
        )
    )
    budget.settle = AsyncMock()
    budget.release = AsyncMock()
    limiter.redis = MagicMock()
    limiter.redis.set = AsyncMock(return_value=True)
    usage = MagicMock()
    usage.session = MagicMock()
    usage.record = AsyncMock()
    usage.delete_session = AsyncMock()
    usage.lock_feedback = AsyncMock(return_value=None)
    audit = MagicMock()
    audit.log_async = AsyncMock()
    settings = SimpleNamespace(
        widget_budget_reservation_tokens=8_000,
        widget_budget_timezone="Europe/Stockholm",
        widget_retrieval_chunks=30,
    )
    service = WidgetAskService(
        user=SimpleNamespace(id=uuid4()),
        assistant_service=assistant_service,
        session_service=session_service,
        widget_limiter=limiter,
        widget_budget=budget,
        widget_usage_repo=usage,
        audit_service=audit,
        settings=settings,
    )
    # Stub the token lookup so the settlement wrapper can be exercised in isolation.
    service._question_tokens = AsyncMock(return_value=tokens)  # type: ignore[method-assign]
    return service, SimpleNamespace(
        assistant_service=assistant_service,
        session_service=session_service,
        limiter=limiter,
        budget=budget,
        usage=usage,
        audit=audit,
        session=session_obj,
    )


class _FakeSessionManager:
    """Minimal stand-in for sessionmanager.session() inside _record_blocked."""

    def __init__(self) -> None:
        self.usage_repo = MagicMock()
        self.usage_repo.record = AsyncMock()
        self.usage_repo.delete_session = AsyncMock()

    def session(self):
        outer = self

        class _Ctx:
            async def __aenter__(self_inner):
                session = MagicMock()

                class _Begin:
                    async def __aenter__(self_b):
                        return None

                    async def __aexit__(self_b, *exc):
                        return False

                session.begin = lambda: _Begin()
                outer.session_obj = session
                return session

            async def __aexit__(self_inner, *exc):
                return False

        return _Ctx()


@pytest.fixture
def fake_db(monkeypatch):
    manager = _FakeSessionManager()
    monkeypatch.setattr(module, "sessionmanager", manager)
    monkeypatch.setattr(
        module, "WidgetUsageRepoImpl", lambda session: manager.usage_repo
    )
    return manager


async def _drain(response):
    return [chunk.text async for chunk in response.answer]


async def test_ask_streams_then_settles_budget_and_records_usage():
    widget = _widget()
    service, deps = _service(tokens=(120, 80))

    response = await service.ask(
        _principal(widget),
        question="  Hej?  ",
        session_id=None,
        client_ip="203.0.113.1",
    )
    assert await _drain(response) == ["Hej", " där"]

    deps.assistant_service.ask.assert_awaited_once()
    kwargs = deps.assistant_service.ask.await_args.kwargs
    assert kwargs["question"] == "Hej?"
    assert kwargs["assistant_id"] == widget.target_id
    assert kwargs["stream"] is True
    assert kwargs["version"] == 2
    assert kwargs["num_chunks_override"] == 30
    assert kwargs["prompt_addendum"] == module.WIDGET_STYLE_PROMPT
    # The assistant as configured: nothing narrows its servers or
    # capabilities, and no approval is requested.
    assert set(kwargs) == {
        "question",
        "assistant_id",
        "session_id",
        "stream",
        "version",
        "num_chunks_override",
        "prompt_addendum",
    }
    assert response.completion_model is None

    deps.budget.reserve.assert_awaited_once_with(widget, 8_000)
    deps.budget.settle.assert_awaited_once()
    assert deps.budget.settle.await_args.args[1:] == (120, 80)
    # Read through the request session to see the uncommitted answer tokens;
    # the budget service commits its accounting independently.
    service._question_tokens.assert_awaited_once_with(  # type: ignore[attr-defined]
        deps.usage.session, response.question_id
    )
    deps.usage.delete_session.assert_not_awaited()


async def _visitor_events(response) -> list[tuple[str, dict]]:
    """The SSE events the public ask route sends for this response."""
    sse = await assistant_protocol.to_conversation_response(
        response=response, stream=True, show_pricing=False
    )
    return [(event.event, json.loads(event.data)) async for event in sse.body_iterator]


CITED_RESOURCE_ID = UUID("a1b2c3d4-0000-4000-8000-000000000001")


def _tool_event() -> Completion:
    return Completion(
        text="",
        response_type=ResponseType.TOOL_CALL,
        tool_calls_metadata=[
            ToolCallMetadata(
                server_name="casefiles",
                tool_name="search",
                arguments={"query": "bibliotek"},
                tool_call_id="call_1",
                result_status="success",
                result=RESOURCE_CONTENT,
                mcp_tool_name="casefiles__search",
                meta={"gen_ai.request.model": "internal"},
            )
        ],
        mcp_tool_references=[
            McpToolReference(
                id=CITED_RESOURCE_ID,
                tool_call_id="call_1",
                mcp_tool_name="casefiles__search",
                uri="https://casefiles.kommun.se/2026-123",
                mime_type="text/plain",
                content=RESOURCE_CONTENT,
                meta={"title": "Ärende 2026-123", "internal_id": 42},
                order=0,
            )
        ],
    )


async def _answer_with_everything():
    yield Completion(
        reasoning_content="Instruktionen säger…", response_type=ResponseType.REASONING
    )
    yield Completion(
        response_type=ResponseType.TOOL_CALL_DELTA,
        tool_call_id="call_1",
        arguments_delta=json.dumps({"query": "bibliotek", "private": RESOURCE_CONTENT}),
    )
    yield _tool_event()
    yield Completion(
        text=f'Hej <inref id="{str(CITED_RESOURCE_ID)[:8]}"/>',
        response_type=ResponseType.TEXT,
        reference_chunks=[_blob()],
    )


async def _ask_as_visitor(widget: Widget) -> list[tuple[str, dict]]:
    service, deps = _service()
    deps.assistant_service.ask.return_value = _ask_result(
        deps.session, _answer_with_everything()
    )
    response = await service.ask(
        _principal(widget), question="Hej?", session_id=None, client_ip=None
    )
    return await _visitor_events(response)


async def test_stream_never_carries_model_reasoning_or_tool_internals():
    events = await _ask_as_visitor(_widget())
    payload = json.dumps(events)

    assert [event for event, _ in events] == [
        "first_chunk",
        "tool_call",
        "tool_call",
        "text",
    ]
    first = events[0][1]
    assert first["completion_model"] is None
    assert first["tools"] == {"assistants": []}
    # Retrieved documents are not listed up front; cited ones come with text.
    assert first["references"] == []
    assert events[3][1]["references"][0]["metadata"]["title"] == "Intern rutin"
    for leaked in (RESOURCE_CONTENT, "llm.internal", "internal_id", "Instruktionen"):
        assert leaked not in payload
    tool = events[1][1]
    assert [call["tool_name"] for call in tool["tools"]] == ["search"]
    assert tool["tools"][0]["meta"] is None
    assert tool["mcp_tool_references"] == []
    # The resource follows once the answer cites it.
    cited = events[2][1]
    assert cited["tools"] == []
    assert cited["mcp_tool_references"][0]["meta"] == {"title": "Ärende 2026-123"}


async def test_hidden_sources_never_leave_the_server():
    events = await _ask_as_visitor(_widget(show_sources=False))
    payload = json.dumps(events)

    assert events[0][1]["references"] == []
    assert all(data.get("references", []) == [] for _, data in events)
    assert all(data.get("mcp_tool_references", []) == [] for _, data in events)
    assert "intranet.kommun.se" not in payload
    assert "casefiles.kommun.se" not in payload
    # Tool activity is still shown.
    assert [event for event, _ in events] == ["first_chunk", "tool_call", "text"]


async def test_hidden_tool_activity_keeps_tool_sources_but_names_no_tool():
    events = await _ask_as_visitor(_widget(show_tool_activity=False))
    payload = json.dumps(events)

    tool_events = [data for event, data in events if event == "tool_call"]
    assert [event["tools"] for event in tool_events] == [[]]
    [ref] = tool_events[0]["mcp_tool_references"]
    assert ref["uri"] == "https://casefiles.kommun.se/2026-123"
    assert ref["tool_call_id"] is None and ref["mcp_tool_name"] is None
    assert "casefiles__search" not in payload
    assert '"search"' not in payload


async def test_restore_never_carries_model_reasoning_or_tool_internals():
    service, deps = _service(session_questions=1)

    session = await service.get_session(_principal(_widget()), uuid4())
    [message] = to_session_public(session).model_dump(mode="json")["messages"]
    payload = json.dumps(message)

    assert message["completion_model"] is None
    assert message["reasoning"] is None
    assert message["tools"] == {"assistants": []}
    assert message["tool_calls"][0]["result"] is None
    assert message["tool_calls"][0]["meta"] is None
    assert message["mcp_tool_references"][0]["content"] is None
    for leaked in (RESOURCE_CONTENT, "llm.internal", "Intern assistent"):
        assert leaked not in payload
    assert message["references"]


async def test_restore_strips_every_reference_when_sources_are_hidden():
    service, _ = _service(session_questions=1)

    session = await service.get_session(
        _principal(_widget(show_sources=False)), uuid4()
    )
    [message] = to_session_public(session).model_dump(mode="json")["messages"]

    assert message["references"] == []
    assert message["mcp_tool_references"] == []
    assert message["tool_calls"]


async def test_restore_strips_tool_calls_when_activity_is_hidden():
    service, _ = _service(session_questions=1)

    session = await service.get_session(
        _principal(_widget(show_tool_activity=False)), uuid4()
    )
    [message] = to_session_public(session).model_dump(mode="json")["messages"]

    assert message["tool_calls"] == []
    assert message["mcp_tool_references"][0]["mcp_tool_name"] is None
    assert message["references"]  # sources still shown


async def test_feedback_response_is_filtered_like_the_restore():
    service, deps = _service(session_questions=1)

    session = await service.leave_feedback(
        _principal(_widget(show_sources=False, show_tool_activity=False)),
        uuid4(),
        SessionFeedback(value=1),
    )
    [message] = to_session_public(session).model_dump(mode="json")["messages"]

    assert message["completion_model"] is None
    assert message["reasoning"] is None
    assert message["references"] == []
    assert message["mcp_tool_references"] == []
    assert message["tool_calls"] == []
    assert (
        deps.session_service.leave_feedback.await_args.kwargs["keep_existing_text"]
        is True
    )


async def test_settlement_reads_the_cumulative_tokens_of_every_provider_round():
    async def row(*values):
        result = MagicMock()
        result.first.return_value = values
        return result

    session = MagicMock()
    # Three tool rounds billed 4 800 prompt tokens; the last request alone
    # had 1 800.
    session.execute = AsyncMock(return_value=await row(4_800, 300, 1_800, 120))
    assert await WidgetAskService._question_tokens(session, uuid4()) == (4_800, 300)

    session.execute = AsyncMock(return_value=await row(None, None, 1_800, 120))
    assert await WidgetAskService._question_tokens(session, uuid4()) == (1_800, 120)

    session.execute = AsyncMock(return_value=await row(None, None, None, None))
    assert await WidgetAskService._question_tokens(session, uuid4()) == (0, 0)


async def test_retention_zero_deletes_the_session_after_streaming():
    widget = _widget(privacy=WidgetPrivacy(retention_days=0))
    service, deps = _service()
    response = await service.ask(
        _principal(widget), question="q", session_id=None, client_ip=None
    )
    await _drain(response)
    deps.usage.delete_session.assert_awaited_once_with(deps.session.id)


async def test_retention_zero_deletes_when_client_leaves_after_first_sse_event():
    service, deps = _service()
    response = await service.ask(
        _principal(_widget(privacy=WidgetPrivacy(retention_days=0))),
        question="q",
        session_id=None,
        client_ip=None,
    )
    answer = response.answer
    assert not isinstance(answer, str)
    stream = await assistant_protocol.to_conversation_response(response, stream=True)

    async def disconnect_after_first_event(message: Message) -> None:
        if message["type"] == "http.response.body":
            raise OSError("visitor disconnected")

    with pytest.raises(OSError, match="visitor disconnected"):
        await stream.stream_response(disconnect_after_first_event)
    deps.usage.delete_session.assert_awaited_once_with(deps.session.id)
    deps.budget.settle.assert_not_awaited()

    # Closing the answer again must not settle its reservation twice.
    await answer.aclose()
    deps.usage.delete_session.assert_awaited_once()


async def test_start_failure_releases_reservation_and_keeps_the_original_as_cause():
    service, deps = _service()
    error = NotFoundException("Assistant deleted")
    deps.assistant_service.ask.side_effect = error
    with pytest.raises(WidgetAnswerUnavailableError) as caught:
        await service.ask(
            _principal(_widget()), question="q", session_id=None, client_ip=None
        )
    assert caught.value.__cause__ is error
    deps.budget.release.assert_awaited_once_with(deps.budget.reserve.return_value)
    deps.budget.settle.assert_not_awaited()


@pytest.mark.parametrize(
    "failure",
    [
        BadRequestException("Completion model gpt-internal is not in space."),
        ModelNotAvailableException("The selected AI model gpt-internal is gone."),
        ProviderInactiveException("Provider Azure Sweden is inactive."),
        OpenAIException(
            "Azure Sweden refused gpt-internal",
            code="provider_error",
            details={"model": "gpt-internal"},
        ),
        ProviderRejectedRequestException("gpt-internal rejected the prompt"),
        RuntimeError("gpt-internal"),
    ],
    ids=lambda failure: type(failure).__name__,
)
async def test_a_failed_turn_tells_the_visitor_nothing_and_logs_the_original(
    failure, monkeypatch
):
    logger = MagicMock()
    monkeypatch.setattr(module, "logger", logger)
    service, deps = _service()
    deps.assistant_service.ask.side_effect = failure

    with pytest.raises(WidgetAnswerUnavailableError) as caught:
        await service.ask(
            _principal(_widget()), question="q", session_id=None, client_ip=None
        )

    error = caught.value
    assert (error.status_code, error.code) == (503, "answer_unavailable")
    body = json.dumps({**error.details(), "code": error.code, "message": error.message})
    assert "gpt-internal" not in body and "Azure" not in body
    assert error.__cause__ is failure
    logger.exception.assert_called_once()
    deps.budget.release.assert_awaited_once()


async def test_a_public_widget_error_from_the_turn_stays_as_it_is(monkeypatch):
    logger = MagicMock()
    monkeypatch.setattr(module, "logger", logger)
    service, deps = _service()
    error = WidgetPublicError("Stopped.", code="stopped")
    deps.assistant_service.ask.side_effect = error

    with pytest.raises(WidgetPublicError) as caught:
        await service.ask(
            _principal(_widget()), question="q", session_id=None, client_ip=None
        )

    assert caught.value is error
    logger.exception.assert_not_called()


async def test_text_held_back_at_the_end_of_the_answer_reaches_the_visitor():
    async def chunks():
        yield Completion(text="Öppet 9–17 ", response_type=ResponseType.TEXT)

    session = _stored_session()
    service, _ = _service(ask_result=_ask_result(session, chunks()))

    response = await service.ask(
        _principal(_widget(show_sources=False)),
        question="q",
        session_id=None,
        client_ip=None,
    )

    assert "".join([chunk.text or "" async for chunk in response.answer]) == (
        "Öppet 9–17 "
    )


async def test_retention_runs_even_when_settlement_fails():
    service, deps = _service()
    deps.budget.settle.side_effect = RuntimeError("Database unavailable")
    response = await service.ask(
        _principal(_widget(privacy=WidgetPrivacy(retention_days=0))),
        question="q",
        session_id=None,
        client_ip=None,
    )
    assert await _drain(response) == ["Hej", " där"]
    deps.usage.delete_session.assert_awaited_once_with(deps.session.id)


async def test_aborted_stream_retains_uncertain_charge_but_deletes_private_content():
    service, deps = _service()
    response = await service.ask(
        _principal(_widget(privacy=WidgetPrivacy(retention_days=0))),
        question="q",
        session_id=None,
        client_ip=None,
    )
    await anext(response.answer)
    await response.answer.aclose()
    deps.budget.settle.assert_not_awaited()
    deps.budget.release.assert_not_awaited()
    deps.usage.delete_session.assert_awaited_once_with(deps.session.id)


async def test_retention_failure_is_not_silently_committed():
    service, deps = _service()
    deps.usage.delete_session.side_effect = RuntimeError("Delete failed")
    response = await service.ask(
        _principal(_widget(privacy=WidgetPrivacy(retention_days=0))),
        question="q",
        session_id=None,
        client_ip=None,
    )
    with pytest.raises(RuntimeError, match="Delete failed"):
        await _drain(response)


async def test_question_limits():
    widget = _widget(limits=WidgetLimits(max_question_chars=100))
    service, _ = _service()
    with pytest.raises(WidgetPublicError) as exc:
        await service.ask(
            _principal(widget), question="   ", session_id=None, client_ip=None
        )
    assert exc.value.code == "question_empty"
    with pytest.raises(WidgetPublicError) as exc:
        await service.ask(
            _principal(widget), question="x" * 101, session_id=None, client_ip=None
        )
    assert exc.value.code == "question_too_long"


async def test_rate_limit_is_recorded_and_re_raised(fake_db):
    widget = _widget()
    service, deps = _service()
    deps.limiter.check_message = AsyncMock(
        side_effect=WidgetRateLimitedError(
            "rate_limited_visitor", retry_after=600, message="m"
        )
    )
    with pytest.raises(WidgetRateLimitedError):
        await service.ask(
            _principal(widget), question="q", session_id=None, client_ip=None
        )
    fake_db.usage_repo.record.assert_awaited_once()
    assert fake_db.usage_repo.record.await_args.kwargs == {
        "blocked_rate": 1,
        "blocked_budget": 0,
    }
    deps.budget.reserve.assert_not_awaited()


async def test_budget_exhaustion_is_recorded_and_audited_once(fake_db):
    widget = _widget()
    service, deps = _service()
    deps.budget.reserve = AsyncMock(
        side_effect=WidgetBudgetExhaustedError(retry_after=100)
    )
    with pytest.raises(WidgetBudgetExhaustedError):
        await service.ask(
            _principal(widget), question="q", session_id=None, client_ip=None
        )
    assert fake_db.usage_repo.record.await_args.kwargs == {
        "blocked_rate": 0,
        "blocked_budget": 1,
    }
    deps.audit.log_async.assert_awaited_once()
    # The visitor's address and browser never enter the tenant's audit trail.
    assert deps.audit.log_async.await_args.kwargs["record_client"] is False

    deps.limiter.redis.set = AsyncMock(return_value=None)  # already audited today
    with pytest.raises(WidgetBudgetExhaustedError):
        await service.ask(
            _principal(widget), question="q", session_id=None, client_ip=None
        )
    deps.audit.log_async.assert_awaited_once()
    deps.assistant_service.ask.assert_not_awaited()


async def test_follow_up_requires_owned_session_and_respects_turn_limit(fake_db):
    widget = _widget(limits=WidgetLimits(max_session_turns=2))
    service, deps = _service(session_questions=2)
    with pytest.raises(WidgetPublicError) as exc:
        await service.ask(
            _principal(widget), question="q", session_id=uuid4(), client_ip=None
        )
    assert exc.value.code == "session_turns_exceeded"
    # The conversation's turn hold never outlives a refused follow-up, and it
    # is released to the marker the hold returned.
    deps.limiter.hold_turn.assert_awaited_once()
    deps.limiter.release_turn.assert_awaited_once()
    assert (
        deps.limiter.release_turn.await_args.args[2]
        is deps.limiter.hold_turn.return_value
    )

    for error in (NotFoundException(), UnauthorizedException("other principal")):
        deps.session_service.get_session_by_uuid = AsyncMock(side_effect=error)
        with pytest.raises(SessionNotOwnedError):
            await service.ask(
                _principal(widget), question="q", session_id=uuid4(), client_ip=None
            )
        with pytest.raises(SessionNotOwnedError):
            await service.get_session(_principal(widget), uuid4())
    # A conversation the visitor does not own is refused before any hold is
    # taken on it: the key is the session id, which its owner's follow-ups use.
    assert deps.limiter.hold_turn.await_count == 1
    assert deps.limiter.release_turn.await_count == 1


async def test_the_turn_hold_is_taken_after_ownership_and_released_to_its_owner():
    widget = _widget()
    service, deps = _service(session_questions=0)
    deps.limiter.hold_turn = AsyncMock(return_value="owner-1")
    session_id = deps.session.id

    response = await service.ask(
        _principal(widget), question="q", session_id=session_id, client_ip=None
    )
    # Read once to check ownership, held, then read again for the turn count.
    assert deps.session_service.get_session_by_uuid.await_count == 2
    deps.limiter.release_turn.assert_not_awaited()
    await _drain(response)
    deps.limiter.release_turn.assert_awaited_once_with(widget, session_id, "owner-1")


def _external_call(**overrides) -> ToolCallMetadata:
    call = dict(
        server_name="casefiles",
        tool_name="create_case",
        tool_call_id="call_9",
        result_status="succeeded",
        is_internal=False,
        purpose=None,
        arguments={"title": "Trasig lampa", "body": "Gatlyktan vid torget är trasig"},
        mcp_tool_name="casefiles__create_case",
    )
    call.update(overrides)
    return ToolCallMetadata(**call)


def _external_event(*calls: ToolCallMetadata) -> Completion:
    return Completion(
        text="", response_type=ResponseType.TOOL_CALL, tool_calls_metadata=list(calls)
    )


async def _external_turn():
    # The model asks for the tool (pending), it is sent to the server
    # (approved, without asking anyone on a visitor turn), the server runs it,
    # the round is reported again, then the answer.
    yield _external_event(_external_call(result_status="pending"))
    yield _external_event(_external_call(result_status="approved"))
    yield _external_event(
        _external_call(),
        _external_call(
            tool_call_id="call_k",
            server_name="knowledge",
            tool_name="search_knowledge",
            is_internal=True,
        ),
        _external_call(
            tool_call_id="call_w",
            server_name="Sökleverantören",
            tool_name="search",
            purpose="web_search",
        ),
        _external_call(tool_call_id="call_d", result_status="denied"),
    )
    yield _external_event(_external_call())
    yield Completion(text="Ärendet är registrerat.", response_type=ResponseType.TEXT)


async def test_every_external_tool_call_of_a_visitor_turn_is_audited_once():
    # Retention 0: nothing of the turn is kept, so the entry is the only trace.
    widget = _widget(privacy=WidgetPrivacy(retention_days=0))
    service, deps = _service(
        ask_result=_ask_result(_stored_session(0), _external_turn())
    )
    principal = _principal(widget)

    response = await service.ask(
        principal, question="Anmäl en trasig lampa", session_id=None, client_ip=None
    )
    assert [text for text in await _drain(response) if text] == [
        "Ärendet är registrerat."
    ]

    deps.audit.log_async.assert_awaited_once()
    kwargs = deps.audit.log_async.await_args.kwargs
    assert kwargs["action"] == ActionType.WIDGET_EXTERNAL_TOOL_CALLED
    assert kwargs["actor_type"] == ActorType.WIDGET_VISITOR
    assert kwargs["actor_id"] is None
    assert kwargs["tenant_id"] == widget.tenant_id
    assert kwargs["entity_id"] == widget.id
    assert kwargs["record_client"] is False
    metadata = kwargs["metadata"]
    assert metadata["public_id"] == widget.public_id
    assert metadata["visitor_id"] == str(principal.visitor_id)
    assert metadata["session_id"] == str(response.session.id)
    assert metadata["question_id"] == str(response.question_id)
    assert metadata["preview"] is False
    assert (
        metadata["tool_call_id"],
        metadata["server_name"],
        metadata["tool_name"],
        metadata["mcp_tool_name"],
        metadata["result_status"],
    ) == ("call_9", "casefiles", "create_case", "casefiles__create_case", "succeeded")
    # The visitor's input is not copied into the trail; the external system
    # has its own record of what it received.
    assert metadata["argument_names"] == ["body", "title"]
    assert "Trasig lampa" not in json.dumps(metadata, ensure_ascii=False)
    deps.usage.delete_session.assert_awaited_once()


async def test_a_failed_external_tool_call_is_audited_too():
    async def turn():
        yield _external_event(_external_call(result_status="approved"))
        yield _external_event(_external_call(result_status="failed"))
        yield Completion(text="Det gick inte.", response_type=ResponseType.TEXT)

    widget = _widget()
    service, deps = _service(ask_result=_ask_result(_stored_session(0), turn()))
    response = await service.ask(
        _principal(widget), question="q", session_id=None, client_ip=None
    )
    await _drain(response)
    deps.audit.log_async.assert_awaited_once()
    assert (
        deps.audit.log_async.await_args.kwargs["metadata"]["result_status"] == "failed"
    )


async def test_a_call_refused_at_the_round_limit_is_not_audited():
    # The last round's calls are refused without being sent, so they fail
    # without ever being approved. Only the call that reached its server counts.
    async def turn():
        yield _external_event(_external_call(result_status="approved"))
        yield _external_event(_external_call())
        yield _external_event(
            _external_call(tool_call_id="call_10", result_status="failed"),
            _external_call(tool_call_id=None, result_status="failed"),
        )
        yield Completion(
            text="Ärendet är registrerat.", response_type=ResponseType.TEXT
        )

    widget = _widget()
    service, deps = _service(ask_result=_ask_result(_stored_session(0), turn()))
    response = await service.ask(
        _principal(widget), question="q", session_id=None, client_ip=None
    )
    await _drain(response)
    deps.audit.log_async.assert_awaited_once()
    metadata = deps.audit.log_async.await_args.kwargs["metadata"]
    assert (metadata["tool_call_id"], metadata["result_status"]) == (
        "call_9",
        "succeeded",
    )


async def test_a_call_id_reused_in_a_later_round_is_audited_per_call():
    # Some providers number their calls per round, so one id can name two calls.
    async def turn():
        for status in ("succeeded", "failed"):
            yield _external_event(_external_call(result_status="approved"))
            yield _external_event(_external_call(result_status=status))
        yield Completion(text="Klart.", response_type=ResponseType.TEXT)

    widget = _widget()
    service, deps = _service(ask_result=_ask_result(_stored_session(0), turn()))
    response = await service.ask(
        _principal(widget), question="q", session_id=None, client_ip=None
    )
    await _drain(response)
    assert [
        (
            call.kwargs["metadata"]["tool_call_id"],
            call.kwargs["metadata"]["result_status"],
        )
        for call in deps.audit.log_async.await_args_list
    ] == [("call_9", "succeeded"), ("call_9", "failed")]


async def test_two_calls_sharing_an_id_in_one_round_are_each_audited():
    close_case = {"tool_name": "close_case", "mcp_tool_name": "casefiles__close_case"}

    async def turn():
        yield _external_event(
            _external_call(result_status="approved"),
            _external_call(**close_case, result_status="approved"),
        )
        yield _external_event(_external_call())
        yield _external_event(_external_call(**close_case, result_status="failed"))
        yield Completion(text="Klart.", response_type=ResponseType.TEXT)

    widget = _widget()
    service, deps = _service(ask_result=_ask_result(_stored_session(0), turn()))
    response = await service.ask(
        _principal(widget), question="q", session_id=None, client_ip=None
    )
    await _drain(response)
    assert [
        (call.kwargs["metadata"]["tool_name"], call.kwargs["metadata"]["result_status"])
        for call in deps.audit.log_async.await_args_list
    ] == [("create_case", "succeeded"), ("close_case", "failed")]


async def test_a_call_the_turn_never_saw_end_is_audited_as_unknown():
    async def turn():
        yield _external_event(_external_call(result_status="approved"))
        yield Completion(text="Jag registrerar", response_type=ResponseType.TEXT)
        yield _external_event(_external_call())

    widget = _widget()
    service, deps = _service(ask_result=_ask_result(_stored_session(0), turn()))
    response = await service.ask(
        _principal(widget, preview=True), question="q", session_id=None, client_ip=None
    )
    # The visitor leaves while the server runs the call.
    await anext(response.answer)
    deps.audit.log_async.assert_not_awaited()
    await response.answer.aclose()

    deps.audit.log_async.assert_awaited_once()
    metadata = deps.audit.log_async.await_args.kwargs["metadata"]
    assert (metadata["tool_call_id"], metadata["result_status"]) == (
        "call_9",
        "unknown",
    )
    assert metadata["preview"] is True


@pytest.mark.parametrize(
    "lost",
    [
        pytest.param(AsyncMock(side_effect=RuntimeError("bug")), id="raised"),
        pytest.param(AsyncMock(return_value=None), id="not enqueued"),
    ],
)
async def test_a_lost_audit_entry_is_logged_and_does_not_cut_the_answer(
    lost, monkeypatch
):
    widget = _widget()
    service, deps = _service(
        ask_result=_ask_result(_stored_session(0), _external_turn())
    )
    deps.audit.log_async = lost
    logger = MagicMock()
    monkeypatch.setattr(module, "logger", logger)
    response = await service.ask(
        _principal(widget), question="q", session_id=None, client_ip=None
    )
    assert [text for text in await _drain(response) if text] == [
        "Ärendet är registrerat."
    ]
    deps.audit.log_async.assert_awaited_once()
    deps.budget.settle.assert_awaited_once()
    # The log keeps what the trail lost, without the visitor's input.
    (record,) = logger.exception.call_args_list + logger.error.call_args_list
    assert record.kwargs["extra"]["tool_call_id"] == "call_9"
    assert record.kwargs["extra"]["argument_names"] == ["body", "title"]


async def _left_with_a_stalled_audit_queue(monkeypatch, widget, *, follow_up=False):
    """The visitor leaves while two external calls run, and the audit queue
    then hangs past the cleanup budget."""

    async def turn():
        yield _external_event(
            _external_call(result_status="approved"),
            _external_call(tool_call_id="call_10", result_status="approved"),
        )
        yield Completion(text="Jag registrerar", response_type=ResponseType.TEXT)

    async def stalled(**_kwargs):
        await anyio.sleep_forever()

    done: list[str] = []

    def write(name):
        async def written(*_args):
            # A real write waits on the database or Redis, where a spent
            # budget cuts it off.
            await asyncio.sleep(0.001)
            done.append(name)

        return written

    monkeypatch.setattr(stream_lifecycle, "FINALIZATION_BUDGET_SECONDS", 0.2)
    logger = MagicMock()
    monkeypatch.setattr(module, "logger", logger)
    service, deps = _service(ask_result=_ask_result(_stored_session(0), turn()))
    deps.audit.log_async = AsyncMock(side_effect=stalled)
    deps.usage.delete_session = AsyncMock(side_effect=write("delete"))
    deps.limiter.hold_turn = AsyncMock(return_value="owner-1")
    deps.limiter.release_turn = AsyncMock(side_effect=write("release"))
    response = await service.ask(
        _principal(widget),
        question="q",
        session_id=deps.session.id if follow_up else None,
        client_ip=None,
    )
    await anext(response.answer)
    await response.answer.aclose()
    return deps, logger, done


async def test_a_stalled_audit_queue_cannot_keep_a_zero_retention_conversation(
    monkeypatch,
):
    widget = _widget(privacy=WidgetPrivacy(retention_days=0))
    _deps, _logger, done = await _left_with_a_stalled_audit_queue(monkeypatch, widget)
    assert done == ["delete"]


async def test_a_stalled_audit_queue_does_not_hold_the_conversation(monkeypatch):
    widget = _widget()
    deps, _logger, done = await _left_with_a_stalled_audit_queue(
        monkeypatch, widget, follow_up=True
    )
    assert done == ["release"]
    deps.limiter.release_turn.assert_awaited_once_with(
        widget, deps.session.id, "owner-1"
    )


async def test_calls_a_stalled_audit_queue_never_recorded_reach_the_log(monkeypatch):
    _deps, logger, _done = await _left_with_a_stalled_audit_queue(
        monkeypatch, _widget()
    )
    extras = [record.kwargs["extra"] for record in logger.error.call_args_list]
    assert [(extra["tool_call_id"], extra["result_status"]) for extra in extras] == [
        ("call_9", "unknown"),
        ("call_10", "unknown"),
    ]
    for extra in extras:
        assert extra["argument_names"] == ["body", "title"]
        assert "Trasig lampa" not in json.dumps(extra, ensure_ascii=False)


async def test_a_turn_without_an_audit_service_still_answers():
    widget = _widget()
    service, _deps = _service(
        ask_result=_ask_result(_stored_session(0), _external_turn())
    )
    service.audit_service = None
    response = await service.ask(
        _principal(widget), question="q", session_id=None, client_ip=None
    )
    assert [text for text in await _drain(response) if text] == [
        "Ärendet är registrerat."
    ]


async def test_feedback_text_is_dropped_unless_stored():
    service, deps = _service()

    await service.leave_feedback(
        _principal(_widget()), uuid4(), SessionFeedback(value=1, text="bra svar")
    )
    assert (
        deps.session_service.leave_feedback.await_args.kwargs["feedback"].text is None
    )

    await service.leave_feedback(
        _principal(_widget(privacy=WidgetPrivacy(store_feedback_text=True))),
        uuid4(),
        SessionFeedback(value=-1, text="fel"),
    )
    assert (
        deps.session_service.leave_feedback.await_args.kwargs["feedback"].text == "fel"
    )


async def test_feedback_moves_the_daily_counters_with_the_vote():
    service, deps = _service()
    widget = _widget()
    principal = _principal(widget)
    session = deps.session_service.get_session_by_uuid.return_value
    order: list[str] = []
    locked_vote: list[int | None] = [None]

    async def lock(_session_id):
        order.append("lock")
        return locked_vote[0]

    async def update(**_kwargs):
        order.append("update")
        return session

    deps.usage.lock_feedback = AsyncMock(side_effect=lock)
    deps.session_service.leave_feedback = AsyncMock(side_effect=update)

    await service.leave_feedback(principal, uuid4(), SessionFeedback(value=1))
    kwargs = deps.usage.record.await_args.kwargs
    assert (kwargs["helpful"], kwargs["unhelpful"]) == (1, 0)
    # The previous vote is read under the row lock, before the update.
    assert order == ["lock", "update"]
    deps.usage.lock_feedback.assert_awaited_once_with(session.id)

    # An overlapping identical vote: the unlocked session object is stale
    # (no vote yet) but the locked read sees the committed vote.
    locked_vote[0] = 1
    session.feedback_value = None
    await service.leave_feedback(principal, uuid4(), SessionFeedback(value=1))
    assert deps.usage.record.await_count == 1

    await service.leave_feedback(principal, uuid4(), SessionFeedback(value=-1))
    kwargs = deps.usage.record.await_args.kwargs
    assert (kwargs["helpful"], kwargs["unhelpful"]) == (-1, 1)


async def test_a_vote_and_its_later_change_are_booked_on_the_conversation_day():
    service, deps = _service()
    principal = _principal(_widget())
    session = deps.session_service.get_session_by_uuid.return_value
    # Monday 00:30 in Stockholm, still Sunday in UTC.
    session.created_at = datetime(2026, 9, 20, 22, 30, tzinfo=timezone.utc)
    monday = date(2026, 9, 21)
    locked_vote: list[int | None] = [None]
    deps.usage.lock_feedback = AsyncMock(side_effect=lambda _id: locked_vote[0])

    await service.leave_feedback(principal, uuid4(), SessionFeedback(value=1))
    # Changed on Tuesday (today, whenever the test runs): the same row.
    locked_vote[0] = 1
    await service.leave_feedback(principal, uuid4(), SessionFeedback(value=-1))

    booked = [
        (call.args[1], call.kwargs["helpful"], call.kwargs["unhelpful"])
        for call in deps.usage.record.await_args_list
    ]
    assert booked == [(monday, 1, 0), (monday, -1, 1)]


async def test_a_persona_name_is_presentation_in_the_prompt_addendum():
    from eneo.widgets.domain.widget import WidgetPersona

    widget = _widget(persona=WidgetPersona(name="Sigge"))
    service, deps = _service(tokens=(1, 1))

    response = await service.ask(
        _principal(widget),
        question="Vem är du?",
        session_id=None,
        client_ip="203.0.113.1",
    )
    await _drain(response)

    addendum = deps.assistant_service.ask.await_args.kwargs["prompt_addendum"]
    assert addendum.startswith(module.WIDGET_STYLE_PROMPT)
    assert 'under the name "Sigge"' in addendum
    assert "remain an AI assistant" in addendum
    assert module.widget_prompt_addendum(_widget()) == module.WIDGET_STYLE_PROMPT
