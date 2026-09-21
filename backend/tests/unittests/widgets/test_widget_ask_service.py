from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import NotFoundException, UnauthorizedException
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
        yield SimpleNamespace(text=text)


def _service(*, ask_result=None, session_questions=0, tokens=(120, 80)):
    assistant_service = MagicMock()
    session_obj = SimpleNamespace(
        id=uuid4(), questions=[object()] * session_questions, feedback_value=None
    )
    assistant_service.ask = AsyncMock(
        return_value=ask_result
        or SimpleNamespace(
            session=session_obj,
            answer=_chunks(),
            question="q",
            question_id=uuid4(),
            completion_model=object(),
        )
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
    assert kwargs["allow_tools"] is False
    assert kwargs["stream"] is True
    assert kwargs["disabled_capabilities"]
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
    feedback = SimpleNamespace(value=1, text="bra svar")
    from eneo.sessions.session import SessionFeedback

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
    del feedback


async def test_feedback_moves_the_daily_counters_with_the_vote():
    from eneo.sessions.session import SessionFeedback

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
