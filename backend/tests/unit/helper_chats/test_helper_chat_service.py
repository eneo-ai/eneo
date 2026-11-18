"""The helper chat mechanics every target shares: what an audit entry records,
what a target without an action for an event leaves out, and the read-only
gates an entry point can ask about."""

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
            mode_changed=None,
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
            mode_changed=None,
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


async def test_a_mode_change_without_an_action_neither_loads_nor_records(
    monkeypatch: pytest.MonkeyPatch,
):
    container = _container(_person())
    target = _target(
        HelperChatAudit(
            entity_type=EntityType.ASSISTANT,
            chat_created=None,
            mode_changed=None,
            conversation_started=None,
            model_changed=None,
        )
    )
    monkeypatch.setattr(helper_chat_service, "target_for", lambda _type: target)

    await helper_chat_service._audit_mode_change(  # pyright: ignore[reportPrivateUsage]
        container, _chat("assistant"), reason="requested"
    )

    target.load.assert_not_awaited()
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
