"""The assistant/space-facing MCP server dict."""

from uuid import uuid4

from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
from eneo.mcp_servers.presentation.assemblers.mcp_server_assembler import (
    MCPServerAssembler,
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
