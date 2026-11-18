"""The assistant as a helper chat's target: who gets a chat on which
assistant, what the refusals say, and how the target answers the chat's
other questions."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from eneo.assistants.application import assistant_helper_chat
from eneo.assistants.application.assistant_helper_chat import (
    ASSISTANT_TARGET,
    AssistantHelperChatErrorCode,
    assistant_chat_availability,
)
from eneo.assistants.assistant import AssistantOrigin
from eneo.audit.domain.entity_types import EntityType
from eneo.database.tables.helper_chats_table import HelperChats
from eneo.helper_chats.personas.assistant import ASSISTANT_INSTRUCTIONS
from eneo.helper_chats.personas.organisation_guidance import (
    with_organisation_guidance,
)
from eneo.helper_chats.targets import HelperChatTargetType, target_for
from eneo.internal_mcp.foundation import request_for_bound_space
from eneo.main.config import get_settings
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.main.models import ResourcePermission

_EDIT = [ResourcePermission.EDIT, ResourcePermission.DELETE]


def _assistant(**overrides) -> SimpleNamespace:
    values = {
        "id": uuid4(),
        "space_id": uuid4(),
        "name": "Ärendehjälpen",
        "hidden": False,
        "origin": AssistantOrigin.USER,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _container(
    *,
    assistant: SimpleNamespace | None = None,
    permissions: list[ResourcePermission] | None = None,
    refused: Exception | None = None,
    owner_id=None,
    help_assistant: bool = False,
) -> MagicMock:
    container = MagicMock()
    container.user.return_value = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    service = container.assistant_service.return_value
    service.helper_chat_owner_id = AsyncMock(return_value=owner_id)
    service.get_assistant = AsyncMock(
        side_effect=refused,
        return_value=(
            assistant or _assistant(),
            _EDIT if permissions is None else permissions,
        ),
    )
    service.is_help_assistant = AsyncMock(return_value=help_assistant)
    return container


def _request() -> MagicMock:
    request = MagicMock()
    request.state = SimpleNamespace()
    return request


async def _refusal(container: MagicMock, target_id=None) -> Exception:
    with pytest.raises(Exception) as refused:
        await ASSISTANT_TARGET.require_edit(container, _request(), target_id or uuid4())
    return refused.value


async def _reason(container: MagicMock, target_id=None) -> str | None:
    return (
        await assistant_chat_availability(
            container, assistant_id=target_id or uuid4(), request=_request()
        )
    ).reason


@pytest.mark.parametrize(
    "container",
    [
        pytest.param(
            lambda: _container(refused=NotFoundException("Assistant not found")),
            id="missing",
        ),
        pytest.param(
            lambda: _container(refused=UnauthorizedException("No reading here")),
            id="unreadable",
        ),
        pytest.param(lambda: _container(permissions=[]), id="read-only"),
        pytest.param(lambda: _container(owner_id=uuid4()), id="another-persons-chat"),
    ],
)
async def test_an_assistant_the_person_may_not_edit_is_refused_alike_however_it_is_out_of_reach(
    container,
):
    refusal = await _refusal(container())

    assert isinstance(refusal, UnauthorizedException)
    assert refusal.code == AssistantHelperChatErrorCode.NO_EDIT_RIGHTS
    assert str(refusal) == "You do not have permission to edit this assistant."
    assert await _reason(container()) == "no_edit_rights"


@pytest.mark.parametrize(
    "container",
    [
        pytest.param(
            lambda: _container(assistant=_assistant(hidden=True)), id="hidden"
        ),
        pytest.param(
            lambda: _container(
                assistant=_assistant(hidden=True, origin=AssistantOrigin.FLOW_MANAGED)
            ),
            id="flow-managed",
        ),
        pytest.param(lambda: _container(help_assistant=True), id="help-assistant"),
    ],
)
async def test_an_assistant_configured_elsewhere_gets_no_chat(container):
    refusal = await _refusal(container())

    assert isinstance(refusal, BadRequestException)
    assert refusal.code == AssistantHelperChatErrorCode.NOT_SUPPORTED
    assert await _reason(container()) == "not_supported"


async def test_the_persons_own_chat_assistant_is_configured_through_its_chat():
    container = _container()
    container.assistant_service.return_value.helper_chat_owner_id = AsyncMock(
        return_value=container.user.return_value.id
    )

    assert (
        await _refusal(container)
    ).code == AssistantHelperChatErrorCode.NOT_SUPPORTED
    container.assistant_service.return_value.get_assistant.assert_not_awaited()


async def test_an_assistant_outside_the_chats_space_is_out_of_reach():
    assistant = _assistant()
    container = _container(assistant=assistant)

    elsewhere = request_for_bound_space(uuid4(), server_name="assistant")
    with pytest.raises(UnauthorizedException):
        await ASSISTANT_TARGET.require_edit(container, elsewhere, assistant.id)
    with pytest.raises(NotFoundException):
        await ASSISTANT_TARGET.require_read(container, elsewhere, assistant.id)

    inside = request_for_bound_space(assistant.space_id, server_name="assistant")
    assert (
        await ASSISTANT_TARGET.require_edit(container, inside, assistant.id)
        is assistant
    )


async def test_a_bound_chat_whose_assistant_cannot_be_read_is_not_found():
    container = _container(refused=UnauthorizedException("No reading here"))

    with pytest.raises(NotFoundException, match="Helper chat not found"):
        await ASSISTANT_TARGET.require_read(container, _request(), uuid4())


def _space(*, default: object | None) -> SimpleNamespace:
    return SimpleNamespace(default=default)


def _available_container(
    monkeypatch: pytest.MonkeyPatch,
    *,
    has_chat: bool,
    may_create: bool,
    default: object | None,
) -> MagicMock:
    container = _container()
    container.space_service.return_value.get_space_access_facts = AsyncMock()
    actor = container.actor_manager.return_value.get_space_actor.return_value
    actor.can_create_assistants.return_value = may_create
    container.space_repo.return_value.one = AsyncMock(
        return_value=_space(default=default)
    )
    monkeypatch.setattr(
        assistant_helper_chat.helper_chat_service,
        "chat_exists",
        AsyncMock(return_value=has_chat),
    )
    monkeypatch.setattr(
        assistant_helper_chat.helper_chat_service,
        "chat_default_model",
        lambda _container, _target, space: space.default,
    )
    return container


async def test_availability_repeats_the_gates_of_opening_a_chat(
    monkeypatch: pytest.MonkeyPatch,
):
    model = object()
    ready = _available_container(
        monkeypatch, has_chat=False, may_create=True, default=model
    )
    assert (
        await assistant_chat_availability(
            ready, assistant_id=uuid4(), request=_request()
        )
    ).model_dump() == {"available": True, "reason": None}

    no_model = _available_container(
        monkeypatch, has_chat=False, may_create=True, default=None
    )
    assert await _reason(no_model) == "no_model"

    # The first chat creates the person's own assistant in the space.
    cannot_create = _available_container(
        monkeypatch, has_chat=False, may_create=False, default=model
    )
    assert await _reason(cannot_create) == "no_edit_rights"

    # A chat that exists already needs nothing created.
    existing = _available_container(
        monkeypatch, has_chat=True, may_create=False, default=model
    )
    assert await _reason(existing) is None
    existing.actor_manager.return_value.get_space_actor.assert_not_called()


def test_the_target_answers_the_chats_other_questions():
    assistant = _assistant()

    assert target_for(HelperChatTargetType.ASSISTANT) is ASSISTANT_TARGET
    assert ASSISTANT_TARGET.starts_in_edit_mode(assistant) is False
    assert ASSISTANT_TARGET.space_id(assistant) == assistant.space_id
    assert ASSISTANT_TARGET.name(assistant) == assistant.name
    assert ASSISTANT_TARGET.require_changeable(assistant) is None
    assert ASSISTANT_TARGET.idle_after() == timedelta(
        minutes=get_settings().flow_authoring_chat_idle_minutes
    )
    assert ASSISTANT_TARGET.audit.entity_type is EntityType.ASSISTANT


async def test_a_mode_change_is_not_fenced():
    container = MagicMock()

    await ASSISTANT_TARGET.fence_mode_change(container, uuid4(), None)

    assert container.mock_calls == []


def test_the_organisation_default_is_the_one_helper_chats_share():
    model_id = uuid4()
    container = MagicMock()
    container.user.return_value = SimpleNamespace(
        tenant=SimpleNamespace(
            flow_settings={"authoring_chat": {"completion_model_id": str(model_id)}}
        )
    )

    assert ASSISTANT_TARGET.organisation_default_model_id(container) == model_id


def _in_organisation(container: MagicMock, helper_chat: dict) -> MagicMock:
    """``container`` with a caller whose organisation has these helper chat
    settings."""
    caller = container.user.return_value
    container.user.return_value = SimpleNamespace(
        **vars(caller),
        tenant=SimpleNamespace(flow_settings={"helper_chat": helper_chat}),
    )
    return container


async def test_turned_off_by_the_organisation_no_chat_is_offered_or_opened():
    # Off answers first, whatever else would stand in the way.
    container = _in_organisation(_container(permissions=[]), {"enabled": False})

    with pytest.raises(UnauthorizedException) as refused:
        await ASSISTANT_TARGET.require_available(container)

    assert refused.value.code == AssistantHelperChatErrorCode.DISABLED
    assert await _reason(container) == "disabled"
    container.assistant_service.return_value.get_assistant.assert_not_called()
    unavailable = ASSISTANT_TARGET.refusals.unavailable("disabled")
    assert isinstance(unavailable, UnauthorizedException)
    assert unavailable.code == AssistantHelperChatErrorCode.DISABLED


async def test_the_chat_is_on_unless_the_organisation_turned_it_off():
    for container in (
        _container(),
        _in_organisation(_container(), {}),
        _in_organisation(_container(), {"enabled": True}),
    ):
        assert await ASSISTANT_TARGET.require_available(container) is None


def test_the_persona_carries_the_organisations_guidance():
    guidance = "Tilltala alltid personen med du."

    assert ASSISTANT_TARGET.instructions(
        _in_organisation(_container(), {"guidance": guidance})
    ) == with_organisation_guidance(ASSISTANT_INSTRUCTIONS, guidance)
    # Without guidance the persona is the code's own, to the byte.
    assert ASSISTANT_TARGET.instructions(_container()) == ASSISTANT_INSTRUCTIONS
    assert (
        ASSISTANT_TARGET.instructions(
            _in_organisation(_container(), {"guidance": "", "enabled": False})
        )
        == ASSISTANT_INSTRUCTIONS
    )


def test_the_target_assistant_is_checked_apart_from_the_chats_own():
    import sqlalchemy as sa

    from eneo.database.tables.assistant_table import Assistants

    tenant_id = uuid4()
    query = (
        sa.select(HelperChats)
        .join(Assistants, Assistants.id == HelperChats.assistant_id)
        .where(ASSISTANT_TARGET.target_exists(tenant_id))
    )
    sql = str(query.compile(dialect=postgresql.dialect()))

    exists = sql.split("EXISTS", 1)[1]
    assert "helper_chat_target_assistant.id = helper_chats.target_id" in exists
    assert "helper_chat_target_assistant.space_id = helper_chats.space_id" in exists
    assert "helper_chat_target_space.tenant_id" in exists
    # The chat's own assistant, joined by the loader, is not what is checked.
    assert "assistants.id = helper_chats.target_id" not in exists


async def test_the_lock_takes_the_assistants_own():
    container = MagicMock()
    container.assistant_service.return_value.lock_assistant = AsyncMock(
        return_value=False
    )
    target_id = uuid4()

    assert await ASSISTANT_TARGET.lock(container, target_id) is False
    container.assistant_service.return_value.lock_assistant.assert_awaited_once_with(
        target_id
    )


async def test_a_turn_gets_the_assistant_settings_tools():
    server = await ASSISTANT_TARGET.build_tool_server(
        token="t", tenant_id=uuid4(), editing=False
    )

    assert server.name == "assistant"
    assert {tool.name for tool in server.tools} == {
        "read_assistant",
        "read_options",
        "read_prompt_history",
        "propose_changes",
    }
