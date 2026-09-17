from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.spaces.space_repo import (
    SpaceRepositoryTenantMismatchError,
    SpaceRepositoryUserRequiredError,
)
from eneo.users.user import UserState


def _tenant(tenant_id):
    return SimpleNamespace(id=tenant_id)


def _user(*, tenant_id):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        tenant=_tenant(tenant_id),
        user_groups_ids=[],
        state=UserState.ACTIVE,
    )


def _repo(*, tenant_id=None, user=None):
    from eneo.spaces.space_repo import SpaceRepository

    return SpaceRepository(
        session=SimpleNamespace(),
        tenant=_tenant(tenant_id or uuid4()),
        user=user,
        factory=SimpleNamespace(),
        file_content_loader=SimpleNamespace(),
        app_repo=SimpleNamespace(),
        assistant_repo=SimpleNamespace(),
        completion_model_repo=SimpleNamespace(),
        transcription_model_repo=SimpleNamespace(),
        embedding_model_repo=SimpleNamespace(),
        http_auth_encryption=SimpleNamespace(),
    )


def test_space_repository_rejects_user_from_different_tenant():
    tenant_id = uuid4()
    user = _user(tenant_id=uuid4())

    with pytest.raises(SpaceRepositoryTenantMismatchError):
        _repo(tenant_id=tenant_id, user=user)


@pytest.mark.asyncio
async def test_tenant_scoped_space_repository_rejects_member_listing_without_user():
    repo = _repo()

    with pytest.raises(SpaceRepositoryUserRequiredError):
        await repo.get_spaces_for_member()


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["general", "web_search"])
async def test_execution_assistant_preserves_mcp_refusal_without_loading_tools(purpose):
    from eneo.database.tables.mcp_server_table import MCPServers
    from eneo.flows.runtime.executor import FlowRunExecutor
    from eneo.main.exceptions import BadRequestException

    repo = _repo()
    space_id = uuid4()
    server = MCPServers(
        id=uuid4(),
        tenant_id=repo.tenant_id,
        name="Execution server",
        http_url="https://example.test/mcp",
        http_auth_type="none",
        purpose=purpose,
        is_enabled=True,
    )
    record = SimpleNamespace(
        id=uuid4(),
        name="Execution assistant",
        logging_enabled=False,
        published=True,
        mcp_servers=[server],
    )
    repo.session = AsyncMock()
    repo.session.scalar.side_effect = [record, None]
    repo._load_assistant_mcp_server_tools_with_overrides = AsyncMock(
        side_effect=AssertionError("Execution must not load MCP tools or policies")
    )

    assistant = await repo.get_execution_assistant(
        space_id=space_id, assistant_id=record.id
    )

    assert assistant is not None
    if purpose == "general":
        assert [item.id for item in assistant.mcp_servers] == [server.id]
        with pytest.raises(BadRequestException, match="Flow MCP is unsupported"):
            FlowRunExecutor._reject_flow_mcp_assistant(assistant)
    else:
        assert assistant.mcp_servers == []
        FlowRunExecutor._reject_flow_mcp_assistant(assistant)
    repo._load_assistant_mcp_server_tools_with_overrides.assert_not_awaited()
