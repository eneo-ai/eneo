from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.assistants.assistant import AssistantOrigin
from intric.assistants.assistant_repo import AssistantRepository
from intric.assistants.assistant_service import AssistantService
from intric.main.exceptions import BadRequestException


def _build_assistant_service_with_mocks(*, origin=AssistantOrigin.USER):
    service = object.__new__(AssistantService)
    assistant_id = uuid4()
    managing_flow_id = uuid4() if origin == AssistantOrigin.FLOW_MANAGED else None
    space = SimpleNamespace(
        id=uuid4(),
        get_assistant=lambda **_: SimpleNamespace(
            id=assistant_id,
            origin=origin,
            managing_flow_id=managing_flow_id,
        ),
    )
    actor = SimpleNamespace(
        can_edit_assistants=lambda: True,
        get_assistant_permissions=lambda assistant: {},
    )
    session = SimpleNamespace(
        scalar=AsyncMock(),
        execute=AsyncMock(),
    )
    service.space_repo = SimpleNamespace(
        get_space_by_assistant=AsyncMock(return_value=space)
    )
    service.actor_manager = SimpleNamespace(
        get_space_actor_from_space=MagicMock(return_value=actor)
    )
    service.repo = SimpleNamespace(session=session, _set_mcp_servers=AsyncMock())
    service.user = SimpleNamespace(tenant_id=uuid4())
    return service, assistant_id, session


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "kwargs", "expected_action"),
    [
        ("add_mcp_to_assistant", {}, "add_mcp_server"),
        ("remove_mcp_from_assistant", {}, "remove_mcp_server"),
        (
            "update_assistant_mcp_config",
            {"enabled": True, "config": {"mode": "safe"}, "priority": 1},
            "update_mcp_server_config",
        ),
    ],
)
async def test_direct_mcp_mutations_reject_flow_managed_assistants(
    method_name, kwargs, expected_action
):
    service, assistant_id, session = _build_assistant_service_with_mocks(
        origin=AssistantOrigin.FLOW_MANAGED
    )

    with pytest.raises(BadRequestException) as exc:
        await getattr(service, method_name)(
            assistant_id=assistant_id,
            mcp_server_id=uuid4(),
            **kwargs,
        )

    assert exc.value.code == "flow_managed_assistant"
    assert exc.value.context["assistant_id"] == str(assistant_id)
    assert exc.value.context["action"] == expected_action
    session.scalar.assert_not_awaited()
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_mcp_to_assistant_rejects_server_not_enabled_for_tenant():
    service, assistant_id, session = _build_assistant_service_with_mocks()
    session.scalar.return_value = None

    with pytest.raises(BadRequestException, match="not enabled for this tenant"):
        await service.add_mcp_to_assistant(
            assistant_id=assistant_id, mcp_server_id=uuid4()
        )

    assert session.scalar.await_count == 1


@pytest.mark.asyncio
async def test_add_mcp_to_assistant_rejects_server_not_assigned_to_space():
    service, assistant_id, session = _build_assistant_service_with_mocks()
    session.scalar.side_effect = [
        SimpleNamespace(id=uuid4()),  # server exists and is enabled
        None,  # missing space mapping
    ]

    with pytest.raises(
        BadRequestException, match="not assigned to this assistant's space"
    ):
        await service.add_mcp_to_assistant(
            assistant_id=assistant_id, mcp_server_id=uuid4()
        )

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


@pytest.mark.asyncio
async def test_set_mcp_servers_prunes_tool_overrides_outside_selected_servers():
    repo = object.__new__(AssistantRepository)
    assistant_in_db = SimpleNamespace(id=uuid4())
    selected_server_id = uuid4()
    session = SimpleNamespace(
        execute=AsyncMock(),
        refresh=AsyncMock(),
    )
    repo.session = session

    await repo.set_mcp_servers(assistant_in_db, [selected_server_id])

    assert session.execute.await_count == 3
    prune_stmt = session.execute.await_args_list[1].args[0]
    compiled = str(prune_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "assistant_mcp_server_tools" in compiled
    assert "mcp_server_tools" in compiled
    assert "NOT IN" in compiled
    assert selected_server_id.hex in compiled
    session.refresh.assert_awaited_once_with(assistant_in_db)


@pytest.mark.asyncio
async def test_set_mcp_servers_clears_tool_overrides_when_no_servers_remain():
    repo = object.__new__(AssistantRepository)
    assistant_in_db = SimpleNamespace(id=uuid4())
    session = SimpleNamespace(
        execute=AsyncMock(),
        refresh=AsyncMock(),
    )
    repo.session = session

    await repo.set_mcp_servers(assistant_in_db, [])

    assert session.execute.await_count == 2
    prune_stmt = session.execute.await_args_list[1].args[0]
    compiled = str(prune_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "assistant_mcp_server_tools" in compiled
    assert "SELECT" not in compiled
    session.refresh.assert_awaited_once_with(assistant_in_db)
