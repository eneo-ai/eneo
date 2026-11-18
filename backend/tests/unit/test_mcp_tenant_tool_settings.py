from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
from eneo.mcp_servers.infrastructure.mappers.mcp_server_mapper import (
    MCPServerToolMapper,
)
from eneo.mcp_servers.infrastructure.repo_impl.mcp_server_repo_impl import (
    apply_tenant_tool_settings,
)


def _tool(enabled: bool) -> MCPServerTool:
    return MCPServerTool(
        id=uuid4(), mcp_server_id=uuid4(), name="tool", is_enabled_by_default=enabled
    )


async def test_tenant_tool_settings_override_tool_defaults():
    tenant_id = uuid4()
    disabled, enabled, other_tenant, unset = (
        _tool(True),
        _tool(False),
        _tool(True),
        _tool(True),
    )
    server = MCPServer(
        tenant_id=tenant_id,
        name="source",
        http_url="https://example.test/mcp",
        tools=[disabled, enabled, other_tenant, unset],
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=[
                (tenant_id, disabled.id, False),
                (tenant_id, enabled.id, True),
                (uuid4(), other_tenant.id, False),
            ]
        )
    )

    result = await apply_tenant_tool_settings(session, [server])

    assert result == [server]
    assert disabled.is_enabled is False
    assert enabled.is_enabled is True
    assert other_tenant.is_enabled is True
    assert unset.is_enabled is True
    # The overlay must not become the value persisted by a tool edit.
    assert MCPServerToolMapper.to_db_dict(disabled)["is_enabled_by_default"] is True
    assert MCPServerToolMapper.to_db_dict(enabled)["is_enabled_by_default"] is False
    session.execute.assert_awaited_once()


async def test_servers_without_tools_skip_the_settings_query():
    session = SimpleNamespace(execute=AsyncMock())
    server = MCPServer(
        tenant_id=uuid4(), name="source", http_url="https://example.test/mcp"
    )

    assert await apply_tenant_tool_settings(session, [server]) == [server]
    session.execute.assert_not_awaited()
