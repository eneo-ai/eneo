# pyright: basic
# FastMCP's Context surface is largely untyped; this module is a thin adapter
# over it, so strict unknown-type checking adds noise without safety here.
"""Shared foundation for eneo's internal (loopback) MCP servers.

An internal MCP server is a FastMCP app the backend both *hosts* (mounted at
``/internal-mcp/<name>``) and *connects to* as an MCP client during a
completion, so built-in tools ride the exact same proxy plumbing as any
external MCP server. Authentication rides in the bearer token: a short-lived
access token that authenticates the user and carries an ``assistant_id``
claim fixing the scope, so tools take no scope arguments and cannot be
pointed at another assistant.

Internal servers are stateless (``stateless_http=True``): no MCP protocol
session id is ever assigned, so the proxy's per-chat-session resume
bookkeeping naturally skips them, and any backend worker can serve a loopback
call regardless of which worker initiated it.

The ephemeral :class:`MCPServer` entities built per completion are never
persisted; failures are local to the request, so circuit-breaker state keyed
on their throwaway ids never accumulates (by design).
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Any, NamedTuple
from uuid import UUID, uuid4

import jwt
from dependency_injector import providers
from mcp.server.fastmcp import Context, FastMCP

from eneo.database.database import sessionmanager
from eneo.main.config import get_settings
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool


class ToolContext(NamedTuple):
    """User-bound DI container + identity for one internal tool call."""

    container: Any
    user: Any
    assistant_id: UUID


def bearer_from_ctx(ctx: Context) -> str:
    request = ctx.request_context.request
    header = request.headers.get("authorization") if request is not None else None
    if not header or not header.lower().startswith("bearer "):
        raise ValueError("Missing or malformed Authorization header.")
    return header.split(" ", 1)[1].strip()


def assistant_id_from_token(token: str) -> UUID:
    settings = get_settings()
    claims = jwt.decode(
        token,
        key=str(settings.jwt_secret),
        audience=settings.jwt_audience,
        algorithms=[settings.jwt_algorithm],
    )
    raw = claims.get("assistant_id")
    if not raw:
        raise ValueError("Access token is not scoped to an assistant.")
    return UUID(str(raw))


@asynccontextmanager
async def internal_tool_context(ctx: Context):
    """Bootstrap a user-bound container for the token's user + assistant.

    Yields :class:`ToolContext`. The container is bound to the authenticated
    user, so loading resources runs the normal permission checks (e.g.
    ``SpaceActor`` for assistants). Internal tools are read-only; the
    transaction simply closes on exit.
    """
    # Imported lazily: the Container pulls in the whole service graph, so a
    # top-level import would create a cycle.
    from eneo.main.container.container import Container
    from eneo.main.container.container_overrides import override_user

    token = bearer_from_ctx(ctx)
    assistant_id = assistant_id_from_token(token)
    async with sessionmanager.session() as session:
        async with session.begin():
            container = Container(session=providers.Object(session))
            user = await container.user_service().authenticate(token=token)
            override_user(container=container, user=user)
            yield ToolContext(container=container, user=user, assistant_id=assistant_id)


def default_page_cap() -> int:
    """Self-cap for paged tool output.

    The proxy's output truncation is destructive (the whole result becomes an
    error blob), so oversized content must be sliced by the tool itself and
    continued via an ``offset`` parameter.
    """
    return min(20_000, get_settings().mcp_tool_output_max_chars // 2)


async def build_ephemeral_server(
    mcp: FastMCP,
    *,
    name: str,
    description: str,
    token: str,
    tenant_id: UUID,
    tool_description_suffixes: Mapping[str, str] | None = None,
) -> MCPServer:
    """Build the ephemeral MCPServer entity a completion attaches for ``mcp``.

    The MCP proxy builds its registry from ``server.tools`` (not a live
    discovery), so the tool entities are derived from ``mcp.list_tools()`` to
    mirror what the endpoint actually exposes. ``tool_description_suffixes``
    appends per-completion enrichment to the named tools' descriptions
    (enrichment only appends; the shared docstring always leads).
    """
    settings = get_settings()
    server_id = uuid4()
    suffixes = tool_description_suffixes or {}
    tools = [
        MCPServerTool(
            mcp_server_id=server_id,
            name=tool.name,
            title=getattr(tool, "title", None),
            description=(
                (tool.description or "") + suffixes[tool.name]
                if tool.name in suffixes
                else tool.description
            ),
            input_schema=tool.inputSchema,
            is_enabled_by_default=True,
        )
        for tool in await mcp.list_tools()
    ]
    return MCPServer(
        id=server_id,
        tenant_id=tenant_id,
        name=name,
        description=description,
        http_url=(
            f"{settings.internal_mcp_base_url.rstrip('/')}/internal-mcp/{name}/mcp"
        ),
        http_auth_type="bearer",
        http_auth_config_schema={"token": token},
        is_enabled=True,
        tools=tools,
    )
