"""The helper chat mechanics every target shares: what an audit entry records,
what a target without an action for an event leaves out, the read-only gates
an entry point can ask about, what edit mode means on a target with and
without modes, when an opening starts a new conversation, and how the
person's conversations are listed."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.database.tables.helper_chats_table import HelperChats
from eneo.helper_chats.application import helper_chat_service
from eneo.helper_chats.targets import (
    HelperChatAudit,
    HelperChatAuditEvent,
    HelperChatTargetType,
    target_for,
)
from eneo.main.exceptions import BadRequestException


def _person() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), username="anna", email="anna@example.org"
    )


def _container(person: SimpleNamespace) -> MagicMock:
    container = MagicMock()
    container.user.return_value = person
    container.audit_service.return_value.log_async = AsyncMock()
    return container


def _target(audit: HelperChatAudit) -> MagicMock:
    target = MagicMock()
    target.audit = audit
    target.load = AsyncMock(return_value=SimpleNamespace(id=uuid4(), name="Mål"))
    return target


def _chat(target_type: str) -> HelperChats:
    return HelperChats(
        session_id=uuid4(),
        assistant_id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        user_id=uuid4(),
        target_type=target_type,
        target_id=uuid4(),
        editing=True,
        mode_changed_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )


async def test_an_event_is_recorded_with_the_person_as_actor_and_the_target_as_entity():
    person = _person()
    container = _container(person)
    event = HelperChatAuditEvent(ActionType.ASSISTANT_UPDATED, "Something happened.")
    target = _target(
        HelperChatAudit(
            entity_type=EntityType.ASSISTANT,
            chat_created=event,
            conversation_started=None,
            model_changed=None,
        )
    )
    target_id = uuid4()

    await helper_chat_service._audit(  # pyright: ignore[reportPrivateUsage]
        container,
        target,
        event,
        target_id=target_id,
        record=SimpleNamespace(id=target_id, name="Ärendehjälpen"),
        extra={"session_id": "s"},
    )

    entry = container.audit_service.return_value.log_async.await_args.kwargs
    assert entry["actor_id"] == person.id
    assert entry["tenant_id"] == person.tenant_id
    assert entry["action"] == ActionType.ASSISTANT_UPDATED
    assert entry["entity_type"] == EntityType.ASSISTANT
    assert entry["entity_id"] == target_id
    assert entry["metadata"]["actor"]["id"] == str(person.id)
    assert entry["metadata"]["extra"] == {"session_id": "s"}


async def test_an_event_the_target_has_no_action_for_is_not_recorded():
    container = _container(_person())
    target = _target(
        HelperChatAudit(
            entity_type=EntityType.ASSISTANT,
            chat_created=None,
            conversation_started=None,
            model_changed=None,
        )
    )

    await helper_chat_service._audit(  # pyright: ignore[reportPrivateUsage]
        container,
        target,
        target.audit.chat_created,
        target_id=uuid4(),
        record=SimpleNamespace(),
        extra={},
    )

    container.audit_service.return_value.log_async.assert_not_awaited()


def test_each_target_type_has_its_target():
    for target_type in HelperChatTargetType:
        assert target_for(target_type).target_type == target_type


def _model(*, tools: bool, access: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        can_access=access,
        supports_tool_calling=tools,
        is_org_default=False,
        created_at=datetime.now(timezone.utc),
    )


def _space(*models: SimpleNamespace) -> SimpleNamespace:
    def select_default(candidates):
        return next(iter(candidates), None)

    return SimpleNamespace(
        completion_models=list(models),
        select_default_completion_model=select_default,
    )


def test_the_default_model_is_one_that_supports_tools_and_none_without():
    target = MagicMock()
    target.organisation_default_model_id.return_value = None
    with_tools = _model(tools=True)

    assert (
        helper_chat_service.chat_default_model(
            MagicMock(), target, _space(_model(tools=False), with_tools)
        )
        is with_tools
    )
    assert (
        helper_chat_service.chat_default_model(
            MagicMock(),
            target,
            _space(_model(tools=False), _model(tools=True, access=False)),
        )
        is None
    )


def _row(target_type: str, *, editing: bool) -> HelperChats:
    chat = _chat(target_type)
    chat.editing = editing
    return chat


def test_a_chat_is_in_edit_mode_only_on_a_target_with_modes():
    flow = target_for(HelperChatTargetType.FLOW)
    assistant = target_for(HelperChatTargetType.ASSISTANT)

    assert flow.modes is not None
    assert assistant.modes is None
    assert helper_chat_service.in_edit_mode(flow, _row("flow", editing=True))
    assert not helper_chat_service.in_edit_mode(flow, _row("flow", editing=False))
    # A row on an assistant that holds edit mode is not in it.
    assert not helper_chat_service.in_edit_mode(
        assistant, _row("assistant", editing=True)
    )


def test_a_turn_runs_in_edit_mode_only_while_the_target_may_change():
    flow = target_for(HelperChatTargetType.FLOW)
    assistant = target_for(HelperChatTargetType.ASSISTANT)
    draft = SimpleNamespace(published_version=None)
    published = SimpleNamespace(published_version=3)
    editing = _row("flow", editing=True)

    assert helper_chat_service.turn_in_edit_mode(flow, editing, draft)
    # A published flow's turn runs as Fråga, and the row keeps its mode.
    assert not helper_chat_service.turn_in_edit_mode(flow, editing, published)
    assert editing.editing is True
    assert not helper_chat_service.turn_in_edit_mode(
        flow, _row("flow", editing=False), draft
    )
    assert not helper_chat_service.turn_in_edit_mode(
        assistant, _row("assistant", editing=True), SimpleNamespace()
    )


async def test_a_turns_binding_takes_its_mode_from_the_target_its_read_loaded(
    monkeypatch: pytest.MonkeyPatch,
):
    container = _container(_person())
    container.session.return_value.scalar = AsyncMock(return_value="flow")
    chat = _row("flow", editing=True)
    load = AsyncMock(return_value=(chat, SimpleNamespace(published_version=1)))
    monkeypatch.setattr(helper_chat_service, "_load_chat", load)

    binding = await helper_chat_service.load_binding(
        container, session_id=chat.session_id, assistant_id=chat.assistant_id
    )

    assert binding.target_type == "flow"
    assert binding.target_id == chat.target_id
    assert binding.editing is False
    # The target the read check loaded answers; nothing more is read.
    load.assert_awaited_once()
    container.session.return_value.scalar.assert_awaited_once()


async def test_a_pause_leaves_a_chat_without_modes_as_it_is(
    monkeypatch: pytest.MonkeyPatch,
):
    measured = AsyncMock(return_value=True)
    monkeypatch.setattr(helper_chat_service, "_idle_since_last_activity", measured)
    container = _container(_person())
    chat = _row("assistant", editing=True)

    await helper_chat_service._leave_edit_mode_after_pause(  # pyright: ignore[reportPrivateUsage]
        container, chat
    )

    assert chat.editing is True
    measured.assert_not_awaited()
    container.session.return_value.scalar.assert_not_called()
    container.audit_service.return_value.log_async.assert_not_awaited()


def _modeless_target() -> MagicMock:
    target = MagicMock(modes=None, target_type=HelperChatTargetType.ASSISTANT)
    target.require_edit = AsyncMock(return_value=SimpleNamespace())
    return target


@pytest.mark.parametrize("editing", [True, False])
async def test_a_mode_change_on_a_target_without_modes_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, editing: bool
):
    container = _container(_person())
    chat = _row("assistant", editing=False)
    monkeypatch.setattr(helper_chat_service, "load_chat", AsyncMock(return_value=chat))
    target = _modeless_target()

    with pytest.raises(TypeError, match="has no modes"):
        await helper_chat_service.update_chat(
            container,
            target,
            target_id=chat.target_id,
            session_id=chat.session_id,
            editing=editing,
        )

    target.require_edit.assert_not_awaited()
    assert chat.editing is False
    container.audit_service.return_value.log_async.assert_not_awaited()


async def test_an_approved_change_needs_edit_access_but_no_mode_without_modes():
    container = _container(_person())
    chat = _row("assistant", editing=False)
    target = _modeless_target()
    record = target.require_edit.return_value

    await helper_chat_service.require_approved_change(container, target, chat)

    target.require_edit.assert_awaited_once()
    assert target.require_edit.await_args.args[2] == chat.target_id
    target.require_changeable.assert_called_once_with(record)


async def test_an_approved_change_on_a_target_with_modes_needs_edit_mode():
    container = _container(_person())
    target = MagicMock()
    target.modes.not_editing.return_value = BadRequestException("Edit mode.")
    target.require_edit = AsyncMock()

    with pytest.raises(BadRequestException, match="Edit mode."):
        await helper_chat_service.require_approved_change(
            container, target, _row("flow", editing=False)
        )
    target.require_edit.assert_not_awaited()


async def test_a_chat_on_a_target_without_modes_never_passes_as_in_edit_mode():
    """A row on such a target that holds edit mode still has no edit mode to
    write in."""
    container = _container(_person())
    target = _modeless_target()

    with pytest.raises(TypeError, match="has no modes"):
        await helper_chat_service.require_edit_mode(
            container, target, _row("assistant", editing=True), change=True
        )
    target.require_edit.assert_not_awaited()


async def test_whether_a_chat_exists_is_asked_for_the_caller_and_the_target():
    person = _person()
    container = _container(person)
    container.session.return_value.scalar = AsyncMock(return_value=True)
    target = MagicMock(target_type=HelperChatTargetType.ASSISTANT)
    target_id = uuid4()

    assert await helper_chat_service.chat_exists(container, target, target_id=target_id)

    query = container.session.return_value.scalar.await_args.args[0]
    params = query.compile().params
    assert person.tenant_id in params.values()
    assert person.id in params.values()
    assert target_id in params.values()
    assert HelperChatTargetType.ASSISTANT in params.values()


def _opening_target() -> MagicMock:
    target = MagicMock(target_type=HelperChatTargetType.ASSISTANT)
    target.require_available = AsyncMock()
    target.require_edit = AsyncMock(return_value=SimpleNamespace())
    target.lock = AsyncMock(return_value=True)
    return target


@pytest.mark.parametrize(
    ("fresh_start", "holds_a_question", "starts"),
    [
        pytest.param(True, True, True, id="fresh-over-a-question"),
        pytest.param(True, False, False, id="fresh-over-an-empty-one"),
        pytest.param(False, True, False, id="resuming"),
    ],
)
async def test_an_opening_starts_a_conversation_only_fresh_over_a_question(
    monkeypatch: pytest.MonkeyPatch,
    fresh_start: bool,
    holds_a_question: bool,
    starts: bool,
):
    container = _container(_person())
    chat = _row("assistant", editing=False)
    container.session.return_value.scalar = AsyncMock(return_value=chat)
    monkeypatch.setattr(helper_chat_service, "load_chat", AsyncMock(return_value=chat))
    asked = AsyncMock(return_value=holds_a_question)
    monkeypatch.setattr(helper_chat_service, "_holds_a_question", asked)
    started = AsyncMock()
    monkeypatch.setattr(helper_chat_service, "_start_conversation", started)
    monkeypatch.setattr(
        helper_chat_service, "_sync_assistant", AsyncMock(return_value=None)
    )

    opened = await helper_chat_service.get_or_create_chat(
        container,
        _opening_target(),
        target_id=chat.target_id,
        request=MagicMock(),
        fresh_start=fresh_start,
    )

    assert opened.chat is chat
    if starts:
        started.assert_awaited_once_with(container, chat, reason="fresh_start")
    else:
        started.assert_not_awaited()
    # A resuming opening never asks what the conversation holds.
    assert asked.await_count == (1 if fresh_start else 0)


async def test_the_conversations_are_read_in_one_query_for_the_caller_and_the_chat(
    monkeypatch: pytest.MonkeyPatch,
):
    person = _person()
    container = _container(person)
    chat = _row("assistant", editing=False)
    read = AsyncMock(return_value=(chat, SimpleNamespace()))
    monkeypatch.setattr(helper_chat_service, "_read_chat", read)
    earlier = uuid4()
    now = datetime.now(timezone.utc)
    result = MagicMock()
    result.all.return_value = [
        (
            chat.session_id,
            now,
            now,
            "Hjälp mig\n  skriva  @[Instruktioner](setting:prompt)",
        ),
        (earlier, now - timedelta(days=1), now - timedelta(days=1), "Vilken modell?"),
    ]
    container.session.return_value.execute = AsyncMock(return_value=result)
    target = _opening_target()

    listed = await helper_chat_service.list_conversations(
        container, target, target_id=chat.target_id, request=MagicMock()
    )

    assert [(item.session_id, item.current) for item in listed] == [
        (chat.session_id, True),
        (earlier, False),
    ]
    assert listed[0].title == "Hjälp mig skriva @[Instruktioner](setting:prompt)"
    # The checks are opening's, and the chat is read without its pause upkeep.
    target.require_available.assert_awaited_once()
    target.require_edit.assert_awaited_once()
    assert read.await_args.kwargs["session_id"] is None
    assert read.await_args.kwargs["target_id"] == chat.target_id
    container.session.return_value.execute.assert_awaited_once()
    query = container.session.return_value.execute.await_args.args[0]
    params = query.compile().params
    assert person.id in params.values()
    assert person.tenant_id in params.values()
    assert chat.assistant_id in params.values()
    assert helper_chat_service.CONVERSATION_LIST_LIMIT in params.values()
