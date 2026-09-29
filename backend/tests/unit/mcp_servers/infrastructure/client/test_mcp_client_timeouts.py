"""Tool-call and transport read timeouts for MCPClient."""

from uuid import uuid4

from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
from eneo.mcp_servers.infrastructure.client.mcp_client import (
    MCP_SSE_READ_TIMEOUT_SECONDS,
    MCP_TOOL_CALL_TIMEOUT_DEFAULT,
    MCPClient,
    transport_read_timeout,
)


def _make_server() -> MCPServer:
    return MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Provider",
        http_url="http://provider.example/mcp",
    )


class TestToolCallTimeout:
    def test_defaults_to_the_global_setting(self):
        assert MCPClient(_make_server(), None).tool_call_timeout == (
            MCP_TOOL_CALL_TIMEOUT_DEFAULT
        )

    def test_per_client_override_wins(self):
        client = MCPClient(_make_server(), None, tool_call_timeout=600)
        assert client.tool_call_timeout == 600


class TestTransportReadTimeout:
    def test_short_tool_call_keeps_the_streaming_floor(self):
        assert transport_read_timeout(60) == MCP_SSE_READ_TIMEOUT_SECONDS

    def test_long_tool_call_raises_the_read_timeout_to_match(self):
        assert transport_read_timeout(600) == 600.0
