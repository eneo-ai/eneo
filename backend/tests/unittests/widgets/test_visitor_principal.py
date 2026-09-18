from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.authentication.auth_models import is_service_api_key, is_widget_visitor
from eneo.sessions import session_service as session_service_module
from eneo.sessions.session_service import SessionService
from eneo.tenants.tenant import TenantInDB
from eneo.widgets.application.visitor_user import build_visitor_user
from eneo.widgets.domain.widget import Widget, WidgetPrivacy


def _widget() -> Widget:
    widget = Widget.create(
        tenant_id=uuid4(), space_id=uuid4(), target_id=uuid4(), name="w"
    )
    return widget.model_copy(update={"id": uuid4()})


def _tenant(tenant_id):
    return TenantInDB.model_construct(
        id=tenant_id,
        name="t",
        quota_limit=0,
        show_model_pricing=False,
        widget_policy={},
    )


def _session_service(user) -> SessionService:
    session = MagicMock()
    session.in_transaction.return_value = True
    return SessionService(
        session_repo=SimpleNamespace(session=session, add=AsyncMock()),
        question_repo=AsyncMock(),
        user=user,
    )


def test_visitor_user_is_synthetic_and_flagged():
    widget = _widget()
    visitor_id = uuid4()
    user = build_visitor_user(widget, visitor_id, _tenant(widget.tenant_id))  # type: ignore[arg-type]

    assert user.id == visitor_id
    assert user.tenant_id == widget.tenant_id
    assert user.permissions == set()
    assert is_widget_visitor(user)
    assert not is_service_api_key(user)
    assert user.active_widget is not None
    assert user.active_widget.space_id == widget.space_id
    assert user.active_widget.target_id == widget.target_id
    assert user.email.endswith("@widget-visitor.eneo")


def test_session_principal_is_widget_plus_visitor():
    widget = _widget()
    visitor_id = uuid4()
    user = build_visitor_user(widget, visitor_id, _tenant(widget.tenant_id))  # type: ignore[arg-type]
    service = _session_service(user)

    assert service._principal_columns() == (None, None, widget.id, visitor_id)

    own = SimpleNamespace(
        widget_id=widget.id, visitor_id=visitor_id, user_id=None, api_key_id=None
    )
    other_visitor = SimpleNamespace(
        widget_id=widget.id, visitor_id=uuid4(), user_id=None, api_key_id=None
    )
    other_widget = SimpleNamespace(
        widget_id=uuid4(), visitor_id=visitor_id, user_id=None, api_key_id=None
    )
    user_session = SimpleNamespace(
        widget_id=None, visitor_id=None, user_id=visitor_id, api_key_id=None
    )
    assert service._is_owner(own)  # type: ignore[arg-type]
    assert not service._is_owner(other_visitor)  # type: ignore[arg-type]
    assert not service._is_owner(other_widget)  # type: ignore[arg-type]
    # A user session whose user_id happens to equal the visitor id is not ours.
    assert not service._is_owner(user_session)  # type: ignore[arg-type]

    session_add = service._build_session_add(
        name="n", assistant_id=widget.target_id, group_chat_id=None
    )
    assert (session_add.user_id, session_add.api_key_id) == (None, None)
    assert (session_add.widget_id, session_add.visitor_id) == (widget.id, visitor_id)


def test_real_user_principal_is_unchanged():
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), active_api_key=None)
    service = _session_service(user)
    assert service._principal_columns() == (user.id, None, None, None)
    assert service._is_owner(
        SimpleNamespace(
            user_id=user.id, api_key_id=None, widget_id=None, visitor_id=None
        )  # type: ignore[arg-type]
    )


class _Begin:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


def _placeholder_harness(monkeypatch):
    """Record which database session each placeholder repository is built on
    and whether a fresh committed session was opened at all."""
    seen: dict[str, object] = {}
    manager_session = MagicMock()
    manager_session.begin = lambda: _Begin()
    manager = SimpleNamespace(used=False)

    class _Ctx:
        async def __aenter__(self):
            manager.used = True
            return manager_session

        async def __aexit__(self, *exc):
            return False

    manager.session = lambda: _Ctx()
    record = SimpleNamespace(id=uuid4(), created_at=None, questions=[])

    def session_repo(session, loader=None):
        seen["session_repo"] = session
        return SimpleNamespace(add=AsyncMock(return_value=record))

    def question_repo(session, loader=None):
        seen["question_repo"] = session
        return SimpleNamespace(add=AsyncMock(return_value=record))

    monkeypatch.setattr(session_service_module, "sessionmanager", manager)
    monkeypatch.setattr(session_service_module, "SessionRepository", session_repo)
    monkeypatch.setattr(session_service_module, "QuestionRepository", question_repo)
    return seen, manager, manager_session


async def test_zero_retention_placeholders_stay_in_the_request_transaction(
    monkeypatch,
):
    widget = _widget().model_copy(update={"privacy": WidgetPrivacy(retention_days=0)})
    user = build_visitor_user(widget, uuid4(), _tenant(widget.tenant_id))  # type: ignore[arg-type]
    assert user.active_widget is not None
    assert user.active_widget.never_persist is True
    service = _session_service(user)
    seen, manager, _ = _placeholder_harness(monkeypatch)
    request_session = service.session_repo.session

    await service.create_session_with_question_placeholder(
        name="q",
        question="q",
        session_assistant_id=widget.target_id,
        question_assistant_id=widget.target_id,
    )
    assert seen["session_repo"] is request_session
    assert seen["question_repo"] is request_session
    assert manager.used is False

    await service.create_question_placeholder(
        question="q2",
        session=SimpleNamespace(id=uuid4()),  # type: ignore[arg-type]
        assistant_id=widget.target_id,
    )
    assert seen["question_repo"] is request_session
    await service.create_session(name="n", assistant_id=widget.target_id)
    assert seen["session_repo"] is request_session
    assert manager.used is False


async def test_retained_widget_placeholders_commit_on_their_own(monkeypatch):
    widget = _widget()
    user = build_visitor_user(widget, uuid4(), _tenant(widget.tenant_id))  # type: ignore[arg-type]
    assert user.active_widget is not None
    assert user.active_widget.never_persist is False
    service = _session_service(user)
    seen, manager, manager_session = _placeholder_harness(monkeypatch)

    await service.create_session_with_question_placeholder(
        name="q",
        question="q",
        session_assistant_id=widget.target_id,
        question_assistant_id=widget.target_id,
    )
    assert manager.used is True
    assert seen["session_repo"] is manager_session
    assert seen["question_repo"] is manager_session
