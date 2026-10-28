from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from eneo.mcp_servers.infrastructure.repo_impl.mcp_server_repo_impl import (
    apply_tenant_tool_settings,
)


def _tool(enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), is_enabled_by_default=enabled)


async def test_tenant_tool_settings_override_tool_defaults():
    tenant_id = uuid4()
    disabled, enabled, other_tenant, unset = (
        _tool(True),
        _tool(False),
        _tool(True),
        _tool(True),
    )
    server = SimpleNamespace(
        tenant_id=tenant_id, tools=[disabled, enabled, other_tenant, unset]
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
    assert disabled.is_enabled_by_default is False
    assert enabled.is_enabled_by_default is True
    assert other_tenant.is_enabled_by_default is True
    assert unset.is_enabled_by_default is True
    session.execute.assert_awaited_once()


async def test_servers_without_tools_skip_the_settings_query():
    session = SimpleNamespace(execute=AsyncMock())
    server = SimpleNamespace(tenant_id=uuid4(), tools=[])

    assert await apply_tenant_tool_settings(session, [server]) == [server]
    session.execute.assert_not_awaited()
