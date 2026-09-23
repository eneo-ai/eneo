import json
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    McpToolReference,
    ResponseType,
    ToolCallMetadata,
)
from eneo.assistants.api import assistant_protocol
from eneo.assistants.api.assistant_models import AssistantResponse
from eneo.info_blobs.info_blob import InfoBlobInDB, InfoBlobInDBWithScore
from eneo.main.exceptions import NotFoundException, UnauthorizedException
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


def _principal(widget: Widget) -> WidgetPrincipal:
    claims = MagicMock(spec=VisitorClaims)
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


async def test_start_failure_releases_reservation_and_preserves_original_error():
    service, deps = _service()
    error = NotFoundException("Assistant deleted")
    deps.assistant_service.ask.side_effect = error
    with pytest.raises(NotFoundException) as caught:
        await service.ask(
            _principal(_widget()), question="q", session_id=None, client_ip=None
        )
    assert caught.value is error
    deps.budget.release.assert_awaited_once_with(deps.budget.reserve.return_value)
    deps.budget.settle.assert_not_awaited()


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

    for error in (NotFoundException(), UnauthorizedException("other principal")):
        deps.session_service.get_session_by_uuid = AsyncMock(side_effect=error)
        with pytest.raises(SessionNotOwnedError):
            await service.ask(
                _principal(widget), question="q", session_id=uuid4(), client_ip=None
            )
        with pytest.raises(SessionNotOwnedError):
            await service.get_session(_principal(widget), uuid4())


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
