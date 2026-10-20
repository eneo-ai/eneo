"""A chat tool call on a plain-http credentialed server explains why it failed."""

from uuid import uuid4

from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session import (
    INSECURE_CREDENTIAL_TRANSPORT_NOTICE,
    MCPProxySession,
)


# Kills: reporting the refusal as the generic "temporarily unavailable" result,
# which tells neither the user nor the model that an admin must switch the
# server address to https.
async def test_tool_call_on_a_legacy_http_row_returns_the_https_notice():
    server_id = uuid4()
    server = MCPServer(
        id=server_id,
        tenant_id=uuid4(),
        name="Legacy",
        http_url="http://mcp.example.org/mcp",
        http_auth_type="bearer",
        tools=[
            MCPServerTool(
                mcp_server_id=server_id,
                name="lookup",
                description="Look something up",
                input_schema={"type": "object", "properties": {}},
            )
        ],
    )
    proxy = MCPProxySession([server], {server_id: {"token": "sk-secret"}})
    tool = proxy.prefixed_tool_name(server_id, "lookup")
    assert tool is not None

    [result] = await proxy.call_tools_parallel([(tool, {})])
    await proxy.close()

    assert result == {
        "content": [{"type": "text", "text": INSECURE_CREDENTIAL_TRANSPORT_NOTICE}],
        "is_error": True,
    }
