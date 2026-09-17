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
    session_obj = SimpleNamespace(id=uuid4(), questions=[object()] * session_questions)
    assistant_service.ask = AsyncMock(
        return_value=ask_result
        or SimpleNamespace(session=session_obj, answer=_chunks(), question="q")
    )
    session_service = MagicMock()
    session_service.get_session_by_uuid = AsyncMock(return_value=session_obj)
    session_service.leave_feedback = AsyncMock(return_value=session_obj)
    limiter = MagicMock()
    limiter.check_message = AsyncMock()
    budget = MagicMock()
    budget.reserve = AsyncMock(
        return_value=BudgetReservation(key="k", reserved_tokens=8_000)
    )
    budget.settle = AsyncMock()
    budget.redis = MagicMock()
    budget.redis.set = AsyncMock(return_value=True)
    usage = MagicMock()
    usage.record = AsyncMock()
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
    # _finish opens its own DB session; stub the token lookup and the
    # session-level usage repo so the wrapper can be exercised in isolation.
    service._last_question_tokens = AsyncMock(return_value=tokens)  # type: ignore[method-assign]
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
    """Minimal stand-in for sessionmanager.session() inside _finish."""

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


async def test_ask_streams_then_settles_budget_and_records_usage(fake_db):
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

    deps.budget.reserve.assert_awaited_once_with(widget, 8_000)
    deps.budget.settle.assert_awaited_once()
    assert deps.budget.settle.await_args.args[1] == 200
    fake_db.usage_repo.record.assert_awaited_once()
    assert fake_db.usage_repo.record.await_args.kwargs["input_tokens"] == 120
    fake_db.usage_repo.delete_session.assert_not_awaited()


async def test_retention_zero_deletes_the_session_after_streaming(fake_db):
    widget = _widget(privacy=WidgetPrivacy(retention_days=0))
    service, deps = _service()
    response = await service.ask(
        _principal(widget), question="q", session_id=None, client_ip=None
    )
    await _drain(response)
    fake_db.usage_repo.delete_session.assert_awaited_once_with(deps.session.id)


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

    deps.budget.redis.set = AsyncMock(return_value=None)  # already audited today
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
