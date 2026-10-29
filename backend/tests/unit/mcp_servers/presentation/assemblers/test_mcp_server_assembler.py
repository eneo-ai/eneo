"""The assistant/space-facing MCP server dict."""

from uuid import uuid4

import pytest

from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
from eneo.mcp_servers.presentation.assemblers.mcp_server_assembler import (
    MCPServerAssembler,
    MCPServerSettingsAssembler,
)
from eneo.mcp_servers.presentation.assemblers.mcp_server_tool_assembler import (
    MCPServerToolAssembler,
)


def _server(**overrides) -> MCPServer:
    server_id = uuid4()
    defaults = dict(
        id=server_id,
        tenant_id=uuid4(),
        name="Provider",
        http_url="http://provider.example/mcp",
        tools=[
            MCPServerTool(
                mcp_server_id=server_id,
                name="tool",
                description="Test tool",
                input_schema={"type": "object", "properties": {}},
            )
        ],
    )
    defaults.update(overrides)
    return MCPServer(**defaults)


class TestToDictWithTools:
    @pytest.mark.parametrize("enabled", [False, True])
    def test_public_responses_keep_effective_enablement(self, enabled):
        server = _server()
        tool = server.tools[0]
        tool.id = uuid4()
        tool.is_enabled_by_default = not enabled
        tool.enabled_override = enabled

        assert (
            MCPServerAssembler.to_dict_with_tools(server)["tools"][0]["is_enabled"]
            is enabled
        )
        assert (
            MCPServerToolAssembler.from_domain_to_model(tool).is_enabled_by_default
            is enabled
        )
        settings = MCPServerSettingsAssembler().from_domain_to_model(server)
        assert settings.tools[0].is_enabled_by_default is enabled
        assert settings.readiness_reason == (None if enabled else "no_approved_tools")
        assert tool.is_enabled_by_default is not enabled

    def test_carries_org_availability(self):
        """A deactivated server stays attached to assistants; the dict says so
        and lets clients render it as unavailable."""
        assert MCPServerAssembler.to_dict_with_tools(_server())["is_enabled"] is True
        assert (
            MCPServerAssembler.to_dict_with_tools(_server(is_enabled=False))[
                "is_enabled"
            ]
            is False
        )

    def test_carries_readiness_reason(self):
        ready = MCPServerAssembler.to_dict_with_tools(_server())
        assert ready["readiness_reason"] is None

        no_tools = MCPServerAssembler.to_dict_with_tools(_server(tools=[]))
        assert no_tools["readiness_reason"] == "no_approved_tools"
