from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.assistants.assistant_repo import AssistantRepository
from intric.assistants.assistant_service import AssistantService
from intric.main.exceptions import BadRequestException


def _build_assistant_service_with_mocks():
    service = object.__new__(AssistantService)
    assistant_id = uuid4()
    space = SimpleNamespace(
        id=uuid4(),
        get_assistant=lambda **_: SimpleNamespace(id=assistant_id),
    )
    actor = SimpleNamespace(
        can_edit_assistants=lambda: True,
        get_assistant_permissions=lambda assistant: {},
    )
    session = SimpleNamespace(
        scalar=AsyncMock(),
        execute=AsyncMock(),
    )
    service.space_repo = SimpleNamespace(get_space_by_assistant=AsyncMock(return_value=space))
    service.actor_manager = SimpleNamespace(
        get_space_actor_from_space=MagicMock(return_value=actor)
    )
    service.repo = SimpleNamespace(session=session, _set_mcp_servers=AsyncMock())
    service.user = SimpleNamespace(tenant_id=uuid4())
    return service, assistant_id, session


@pytest.mark.asyncio
async def test_add_mcp_to_assistant_rejects_server_not_enabled_for_tenant():
    service, assistant_id, session = _build_assistant_service_with_mocks()
    session.scalar.return_value = None

    with pytest.raises(BadRequestException, match="not enabled for this tenant"):
        await service.add_mcp_to_assistant(assistant_id=assistant_id, mcp_server_id=uuid4())

    assert session.scalar.await_count == 1


@pytest.mark.asyncio
async def test_add_mcp_to_assistant_rejects_server_not_assigned_to_space():
    service, assistant_id, session = _build_assistant_service_with_mocks()
    session.scalar.side_effect = [
        SimpleNamespace(id=uuid4()),  # server exists and is enabled
        None,  # missing space mapping
    ]

    with pytest.raises(BadRequestException, match="not assigned to this assistant's space"):
        await service.add_mcp_to_assistant(assistant_id=assistant_id, mcp_server_id=uuid4())

    assert session.scalar.await_count == 2


@pytest.mark.asyncio
async def test_assistant_repo_rejects_tool_overrides_outside_assigned_servers():
    repo = object.__new__(AssistantRepository)
    assistant_in_db = SimpleNamespace(id=uuid4())
    valid_server_id = uuid4()
    invalid_tool_id = uuid4()

    session = SimpleNamespace(refresh=AsyncMock())
    call_count = 0

    async def _execute(_stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            result = MagicMock()
            result.fetchall.return_value = [(valid_server_id,)]
            return result
        if call_count == 3:
            result = MagicMock()
            result.fetchall.return_value = []
            return result
        return MagicMock()

    session.execute = _execute
    repo.session = session

    with pytest.raises(
        BadRequestException,
        match="outside assistant MCP servers",
    ):
        await repo._set_mcp_tools(assistant_in_db, [(invalid_tool_id, True)])


@pytest.mark.asyncio
async def test_assistant_repo_accepts_tool_overrides_within_assigned_servers():
    repo = object.__new__(AssistantRepository)
    assistant_in_db = SimpleNamespace(id=uuid4())
    valid_server_id = uuid4()
    valid_tool_id = uuid4()

    session = SimpleNamespace(refresh=AsyncMock())
    call_count = 0

    async def _execute(_stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            result = MagicMock()
            result.fetchall.return_value = [(valid_server_id,)]
            return result
        if call_count == 3:
            result = MagicMock()
            result.fetchall.return_value = [(valid_tool_id,)]
            return result
        return MagicMock()

    session.execute = _execute
    repo.session = session

    await repo._set_mcp_tools(assistant_in_db, [(valid_tool_id, False)])

    assert call_count == 4
    session.refresh.assert_awaited_once_with(assistant_in_db)
