from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from intric.mcp_servers.application.mcp_server_settings_service import (
    MCPServerSettingsService,
)


async def test_available_servers_apply_tenant_tool_overrides():
    tenant_id = uuid4()
    tool_id = uuid4()
    tool = SimpleNamespace(id=tool_id, is_enabled_by_default=True)
    server = SimpleNamespace(
        tools=[tool],
        env_vars=None,
    )

    settings_result = SimpleNamespace(all=lambda: [(tool_id, False)])
    repo = SimpleNamespace(
        query_by_tenant=AsyncMock(return_value=[server]),
        session=SimpleNamespace(execute=AsyncMock(return_value=settings_result)),
    )
    service = MCPServerSettingsService(
        mcp_server_repo=repo,
        user=SimpleNamespace(tenant_id=tenant_id),
    )

    result = await service.get_available_mcp_servers()

    assert result == [server]
    assert tool.is_enabled_by_default is False
    repo.session.execute.assert_awaited_once()
