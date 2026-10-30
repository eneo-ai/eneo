from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.assistants.assistant import AssistantOrigin
from eneo.assistants.assistant_repo import AssistantRepository
from eneo.assistants.assistant_service import AssistantService
from eneo.main.exceptions import BadRequestException


def _build_assistant_service_with_mocks(
    *,
    origin=AssistantOrigin.USER,
    is_personal=True,
    server_in_space=False,
):
    service = object.__new__(AssistantService)
    assistant_id = uuid4()
    managing_flow_id = uuid4() if origin == AssistantOrigin.FLOW_MANAGED else None
    assistant = SimpleNamespace(
        id=assistant_id,
        is_default=True,
        mcp_servers=[],
        origin=origin,
        managing_flow_id=managing_flow_id,
    )
    space = SimpleNamespace(
        id=uuid4(),
        get_assistant=lambda **_: assistant,
        is_personal=lambda: is_personal,
        is_mcp_server_in_space=lambda _server_id: server_in_space,
        mcp_servers=[],
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
        get_space_by_assistant=AsyncMock(return_value=space),
        project_assistant_mcp_servers=AsyncMock(
            side_effect=lambda **kwargs: kwargs["mcp_servers"]
        ),
    )
    service.actor_manager = SimpleNamespace(
        get_space_actor_from_space=MagicMock(return_value=actor)
    )
    service.repo = SimpleNamespace(
        session=session,
        lock=AsyncMock(),
        add_mcp_server=AsyncMock(),
    )
    service.user = SimpleNamespace(tenant_id=uuid4())
    service.skill_service = SimpleNamespace(ensure_runtime_policy=AsyncMock())
    service.effective_config_service = None
    service._validate_attachments_fit = AsyncMock()
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
    # Only the fit lock an addition takes first may run; no association is
    # read or written.
    session.scalar.assert_not_awaited()
    assert session.execute.await_count <= 1
    service.repo.add_mcp_server.assert_not_awaited()


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
async def test_add_mcp_to_assistant_rejects_server_not_in_shared_space():
    # Shared (non-personal) space: a tenant-enabled server that is not a member
    # of the space is still rejected. Membership now comes from the space read
    # model (space.is_mcp_server_in_space), so no spaces_mcp_servers round-trip
    # is issued — only the tenant-enablement query hits the DB.
    service, assistant_id, session = _build_assistant_service_with_mocks(
        is_personal=False, server_in_space=False
    )
    session.scalar.return_value = SimpleNamespace(
        id=uuid4(), purpose="general"
    )  # server is enabled

    with pytest.raises(
        BadRequestException, match="not assigned to this assistant's space"
    ):
        await service.add_mcp_to_assistant(
            assistant_id=assistant_id, mcp_server_id=uuid4()
        )

    assert session.scalar.await_count == 1


@pytest.mark.asyncio
async def test_add_mcp_to_assistant_allows_personal_space_server_enabled_after_creation():
    # Regression for #500: a personal space exposes every tenant-enabled server
    # via the read model (space.is_mcp_server_in_space -> True), even though the
    # stale spaces_mcp_servers table holds no row for a server enabled after the
    # space was created. The assignment must succeed, without a spaces_mcp_servers
    # round-trip (server lookup + assistant row only).
    service, assistant_id, session = _build_assistant_service_with_mocks(
        is_personal=True, server_in_space=True
    )
    mcp_server_id = uuid4()
    mcp_server = SimpleNamespace(id=mcp_server_id)
    existing_mcp_server = SimpleNamespace(id=uuid4())
    service.space_repo.get_space_by_assistant.return_value.get_assistant(
        assistant_id=assistant_id
    ).mcp_servers = [existing_mcp_server]
    service.space_repo.get_space_by_assistant.return_value.mcp_servers = [mcp_server]
    assistant_in_db = SimpleNamespace(id=assistant_id)
    session.scalar.side_effect = [
        SimpleNamespace(
            id=mcp_server_id, purpose="general"
        ),  # server exists and is enabled
        assistant_in_db,  # assistant row for set_mcp_servers
    ]
    result = MagicMock()
    result.scalars.return_value = [
        SimpleNamespace(mcp_server_id=existing_mcp_server.id)
    ]
    session.execute.return_value = result

    await service.add_mcp_to_assistant(
        assistant_id=assistant_id,
        mcp_server_id=mcp_server_id,
    )

    assert session.scalar.await_count == 1
    service.repo.add_mcp_server.assert_awaited_once_with(
        assistant_id,
        service.space_repo.get_space_by_assistant.return_value.id,
        mcp_server_id,
    )
    service.space_repo.project_assistant_mcp_servers.assert_awaited_once_with(
        space_id=service.space_repo.get_space_by_assistant.return_value.id,
        assistant_id=assistant_id,
        mcp_servers=[existing_mcp_server, mcp_server],
    )
    service._validate_attachments_fit.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_mcp_to_assistant_skips_space_mapping_when_governed():
    service, assistant_id, session = _build_assistant_service_with_mocks()
    mcp_server_id = uuid4()
    mcp_server = SimpleNamespace(id=mcp_server_id)
    assistant_in_db = SimpleNamespace(id=assistant_id)
    service.effective_config_service = AsyncMock(
        resolve_for=AsyncMock(
            return_value=SimpleNamespace(
                mcp_enforced=True,
                available_mcp_servers=[mcp_server],
            )
        )
    )
    session.scalar.side_effect = [
        SimpleNamespace(id=mcp_server_id, purpose="general"),
        assistant_in_db,
    ]
    result = MagicMock()
    result.scalars.return_value = []
    session.execute.return_value = result

    await service.add_mcp_to_assistant(
        assistant_id=assistant_id,
        mcp_server_id=mcp_server_id,
    )

    assert session.scalar.await_count == 1
    service.repo.add_mcp_server.assert_awaited_once_with(
        assistant_id,
        service.space_repo.get_space_by_assistant.return_value.id,
        mcp_server_id,
    )


@pytest.mark.asyncio
async def test_prune_keeps_only_tool_overrides_inside_selected_servers():
    repo = object.__new__(AssistantRepository)
    selected_server_id = uuid4()
    repo.session = SimpleNamespace(execute=AsyncMock())

    await repo._prune_mcp_tool_overrides(uuid4(), [selected_server_id])

    prune_stmt = repo.session.execute.await_args.args[0]
    compiled = str(prune_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "assistant_mcp_server_tools" in compiled
    assert "mcp_server_tools" in compiled
    assert "NOT IN" in compiled
    assert selected_server_id.hex in compiled


@pytest.mark.asyncio
async def test_prune_clears_every_tool_override_when_no_servers_remain():
    repo = object.__new__(AssistantRepository)
    repo.session = SimpleNamespace(execute=AsyncMock())

    await repo._prune_mcp_tool_overrides(uuid4(), [])

    prune_stmt = repo.session.execute.await_args.args[0]
    compiled = str(prune_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "assistant_mcp_server_tools" in compiled
    assert "SELECT" not in compiled
