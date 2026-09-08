"""A built-in provider exposes the running loopback server's tool definitions,
keeping only the administrator's per-tool decisions from the persisted rows."""

from uuid import uuid4

from eneo.internal_mcp.builtin_tools import with_live_builtin_tools
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool


def _server(*, http_auth_type: str, purpose: str, tools: list[MCPServerTool]):
    return MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Images",
        http_url="http://localhost/internal-mcp/image_generation/mcp",
        http_auth_type=http_auth_type,
        purpose=purpose,
        tools=tools,
    )


def _stale_generate_image(server_id, **overrides) -> MCPServerTool:
    return MCPServerTool(
        id=uuid4(),
        mcp_server_id=server_id,
        name="generate_image",
        description="Generate an image from a text description.",
        input_schema={"type": "object", "properties": {"prompt": {"type": "string"}}},
        **overrides,
    )


async def test_builtin_provider_gets_the_live_schema_with_admin_decisions_kept():
    server_id = uuid4()
    stale = _stale_generate_image(
        server_id, display_name="Skapa bild", is_enabled_by_default=False
    )
    server = _server(http_auth_type="internal", purpose="image_generation", tools=[])
    server.id = server_id
    server.tools = [stale]

    tools = await with_live_builtin_tools(server)

    (tool,) = tools
    assert tool.id == stale.id
    assert tool.mcp_server_id == server_id
    assert "reference_images" in (tool.input_schema or {})["properties"]
    assert tool.description != stale.description
    assert tool.display_name == "Skapa bild"
    assert tool.is_enabled_by_default is False


async def test_live_tool_without_a_persisted_row_is_exposed_enabled():
    server = _server(http_auth_type="internal", purpose="image_generation", tools=[])

    tools = await with_live_builtin_tools(server)

    assert [tool.name for tool in tools] == ["generate_image"]
    assert tools[0].is_enabled_by_default is True


async def test_external_provider_keeps_its_persisted_tools():
    server = _server(http_auth_type="bearer", purpose="image_generation", tools=[])
    stale = _stale_generate_image(server.id)
    server.tools = [stale]

    assert await with_live_builtin_tools(server) == [stale]


async def test_builtin_without_a_loopback_of_its_purpose_keeps_persisted_tools():
    server = _server(http_auth_type="internal", purpose="web_search", tools=[])
    stale = _stale_generate_image(server.id)
    server.tools = [stale]

    assert await with_live_builtin_tools(server) == [stale]
