from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from eneo.internal_mcp.foundation import build_ephemeral_server


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
