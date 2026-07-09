"""Registry of eneo's internal (loopback) MCP servers.

One entry per server: the FastMCP instance and its eagerly built
Streamable-HTTP ASGI app. The registry drives both the FastAPI mounts and the
parent-app lifespan, so adding a server here is all the hosting-side wiring a
new internal tool needs.
"""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette

from eneo.internal_mcp.files import FILES_SERVER_NAME
from eneo.internal_mcp.files import mcp as files_mcp
from eneo.internal_mcp.knowledge import KNOWLEDGE_SERVER_NAME
from eneo.internal_mcp.knowledge import mcp as knowledge_mcp


@dataclass(frozen=True)
class InternalMCP:
    name: str
    mcp: FastMCP
    app: Starlette


# Apps are built eagerly so ``mcp.session_manager`` exists before the lifespan
# below runs. Each app is mounted at "/internal-mcp/{name}"; its own route is
# "/mcp", so a server's full loopback URL is "<base>/internal-mcp/{name}/mcp".
INTERNAL_MCP_SERVERS: tuple[InternalMCP, ...] = (
    InternalMCP(
        name=KNOWLEDGE_SERVER_NAME,
        mcp=knowledge_mcp,
        app=knowledge_mcp.streamable_http_app(),
    ),
    InternalMCP(
        name=FILES_SERVER_NAME,
        mcp=files_mcp,
        app=files_mcp.streamable_http_app(),
    ),
)


def internal_mcp_mounts() -> list[tuple[str, Starlette]]:
    """``(mount path, ASGI app)`` pairs for the FastAPI app's ``mount`` calls."""
    return [
        (f"/internal-mcp/{server.name}", server.app) for server in INTERNAL_MCP_SERVERS
    ]


@asynccontextmanager
async def internal_mcp_lifespan():
    """Run every internal server's Streamable-HTTP session manager.

    Mounted sub-apps do not get their lifespan invoked by Starlette, so the
    parent app's lifespan must drive the session managers.
    """
    async with AsyncExitStack() as stack:
        for server in INTERNAL_MCP_SERVERS:
            await stack.enter_async_context(server.mcp.session_manager.run())
        yield
