from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from eneo.internal_mcp.foundation import build_ephemeral_server
from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session import (
    declares_destructive,
)


async def test_ephemeral_server_tools_keep_the_annotations_they_declare():
    """A tool's explicit MCP annotations reach the turn's tool list, so a tool
    that declares itself destructive is asked about; a tool that declares
    none carries none."""
    mcp = FastMCP("flows")

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
    async def acts() -> str:
        return "done"

    @mcp.tool()
    async def reads() -> str:
        return "read"

    server = await build_ephemeral_server(
        mcp,
        name="flows",
        description="Loopback",
        token="token",
        tenant_id=uuid4(),
    )

    tools = {tool.name: tool for tool in server.tools}
    assert tools["acts"].annotations == {"destructiveHint": True}
    assert declares_destructive(tools["acts"]) is True
    assert tools["reads"].annotations is None
    assert declares_destructive(tools["reads"]) is False


async def test_ephemeral_loopback_server_is_marked_internal():
    """The loopback factory is the only place that sets ``is_internal``: it is
    what distinguishes Eneo's own tools from an external server that happens
    to carry the same name."""
    server = await build_ephemeral_server(
        FastMCP("knowledge"),
        name="knowledge",
        description="Loopback",
        token="token",
        tenant_id=uuid4(),
    )

    assert server.is_internal is True
    assert server.name == "knowledge"
