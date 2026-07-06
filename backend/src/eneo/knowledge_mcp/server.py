# pyright: basic
# FastMCP's Context surface is largely untyped; this module is a thin adapter
# over it, so strict unknown-type checking adds noise without safety here.
"""FastMCP loopback server + ephemeral-server builder for knowledge search.

The same process both *hosts* this MCP server (mounted at
``/internal-mcp/knowledge``) and *connects* to it as an MCP client during a
completion, so built-in knowledge search rides the exact same proxy plumbing as
any external MCP server. Authentication rides in the bearer token: a
short-lived access token that authenticates the user and carries an
``assistant_id`` claim identifying whose knowledge may be searched. Tools
therefore take no scope argument and cannot be pointed at another assistant.

The server is stateless (``stateless_http=True``): no MCP protocol session id
is ever assigned, so the proxy's per-chat-session resume bookkeeping naturally
skips it, and any backend worker can serve a loopback call regardless of which
worker initiated it.

The ephemeral :class:`MCPServer` entity built per completion is never
persisted; failures are local to the request, so circuit-breaker state keyed on
its throwaway id never accumulates (by design).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import jwt
from dependency_injector import providers
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import EmbeddedResource, TextContent, TextResourceContents
from pydantic import AnyUrl

from eneo.database.database import sessionmanager
from eneo.main.config import get_settings
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool

logger = logging.getLogger(__name__)

# Name of the ephemeral MCP server eneo attaches for knowledge search. The MCP
# proxy prefixes tools with a sanitized form of this (``knowledge__search_knowledge``).
KNOWLEDGE_SERVER_NAME = "knowledge"

# Ceiling on chunks returned per call regardless of what the model asks for.
# The model can always call again with a refined query; the proxy additionally
# truncates oversized tool output.
MAX_RESULTS_CEILING = 20

mcp = FastMCP(
    name="Eneo Knowledge",
    stateless_http=True,
    instructions=(
        "Tools for searching the knowledge sources attached to this Eneo "
        "assistant. The searchable scope is fixed by the access token; tools "
        "take no assistant id."
    ),
)


# --------------------------------------------------------------------------- #
# Request context helpers
# --------------------------------------------------------------------------- #
def _bearer_from_ctx(ctx: Context) -> str:
    request = ctx.request_context.request
    header = request.headers.get("authorization") if request is not None else None
    if not header or not header.lower().startswith("bearer "):
        raise ValueError("Missing or malformed Authorization header.")
    return header.split(" ", 1)[1].strip()


def _assistant_id_from_token(token: str) -> UUID:
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
async def _knowledge_context(ctx: Context):
    """Bootstrap a user-bound container for the token's user + assistant.

    Yields ``(container, assistant_id)``. The container is bound to the
    authenticated user, so loading the assistant runs the normal ``SpaceActor``
    permission checks. Search is read-only; the transaction simply closes on
    exit.
    """
    # Imported lazily: the Container pulls in the whole service graph, so a
    # top-level import would create a cycle.
    from eneo.main.container.container import Container
    from eneo.main.container.container_overrides import override_user

    token = _bearer_from_ctx(ctx)
    assistant_id = _assistant_id_from_token(token)
    async with sessionmanager.session() as session:
        async with session.begin():
            container = Container(session=providers.Object(session))
            user = await container.user_service().authenticate(token=token)
            override_user(container=container, user=user)
            yield container, assistant_id


def _pick_embedding_model(assistant):
    """First-non-empty pick, mirroring ReferencesService."""
    if assistant.collections:
        return assistant.collections[0].embedding_model
    if assistant.websites:
        return assistant.websites[0].embedding_model
    if assistant.integration_knowledge_list:
        return assistant.integration_knowledge_list[0].embedding_model
    return None


def _clamp_max_results(max_results: int) -> int:
    return max(1, min(max_results, MAX_RESULTS_CEILING))


def _search_result_content(query: str, chunks) -> list[TextContent | EmbeddedResource]:
    """Convert search hits to MCP content blocks.

    Each chunk becomes an ``EmbeddedResource`` so the completion layer's
    tool-result reference handling picks it up and the answer can cite it.
    """
    if not chunks:
        return [
            TextContent(
                type="text",
                text=f"No results for '{query}' in this assistant's knowledge.",
            )
        ]

    content: list[TextContent | EmbeddedResource] = [
        TextContent(
            type="text",
            text=f"{len(chunks)} result(s) for '{query}':",
        )
    ]
    for chunk in chunks:
        title = chunk.info_blob_title or "Untitled source"
        content.append(
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(
                    uri=AnyUrl(
                        f"eneo://info-blob/{chunk.info_blob_id}#chunk-{chunk.chunk_no}"
                    ),
                    mimeType="text/plain",
                    text=f"Title: {title}\n\n{chunk.text}",
                    _meta={
                        "info_blob_id": str(chunk.info_blob_id),
                        "score": chunk.score,
                    },
                ),
            )
        )
    return content


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
@mcp.tool(title="Search knowledge")
async def search_knowledge(
    query: str,
    ctx: Context,
    max_results: int = 8,
) -> list[TextContent | EmbeddedResource]:
    """Semantically search this assistant's knowledge sources.

    Returns the most relevant text passages. Use a focused, self-contained
    query (not the user's whole message); call again with a refined query if
    the results do not answer the question.
    """
    max_results = _clamp_max_results(max_results)
    async with _knowledge_context(ctx) as (container, assistant_id):
        assistant, _ = await container.assistant_service().get_assistant(assistant_id)
        embedding_model = _pick_embedding_model(assistant)
        if embedding_model is None:
            return [
                TextContent(
                    type="text",
                    text="This assistant has no knowledge sources attached.",
                )
            ]

        chunks = await container.datastore().semantic_search(
            query,
            embedding_model=embedding_model,
            collections=assistant.collections,
            websites=assistant.websites,
            integration_knowledge_list=assistant.integration_knowledge_list,
            num_chunks=max_results,
            autocut_cutoff=None,
        )

    return _search_result_content(query, chunks)


@mcp.tool(title="List knowledge sources")
async def list_knowledge_sources(ctx: Context) -> str:
    """List the knowledge sources attached to this assistant."""
    async with _knowledge_context(ctx) as (container, assistant_id):
        assistant, _ = await container.assistant_service().get_assistant(assistant_id)

        lines: list[str] = []
        for collection in assistant.collections:
            lines.append(
                f"- Collection '{collection.name}'"
                f" ({collection.num_info_blobs} documents)"
            )
        for website in assistant.websites:
            name = website.name or website.url
            lines.append(f"- Website '{name}' ({website.url})")
        for knowledge in assistant.integration_knowledge_list:
            lines.append(f"- Integration '{knowledge.name}'")

    if not lines:
        return "This assistant has no knowledge sources attached."
    return "Knowledge sources searchable with search_knowledge:\n" + "\n".join(lines)


# --------------------------------------------------------------------------- #
# ASGI app + lifespan + ephemeral-server builder
# --------------------------------------------------------------------------- #
# Build the Streamable-HTTP ASGI app eagerly so ``mcp.session_manager`` exists
# for the lifespan below. Mounted at "/internal-mcp/knowledge"; its own route
# is "/mcp", so the full loopback URL is "<base>/internal-mcp/knowledge/mcp".
knowledge_mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def knowledge_mcp_lifespan():
    """Run the Streamable-HTTP session manager for the lifetime of the app.

    Mounted sub-apps do not get their lifespan invoked by Starlette, so the
    parent app's lifespan must drive the session manager's task group.
    """
    async with mcp.session_manager.run():
        yield


async def _knowledge_tool_entities(server_id: UUID) -> list[MCPServerTool]:
    """Derive entity-side tool definitions from the live FastMCP tool list.

    The MCP proxy builds its registry from ``server.tools`` (not a live
    discovery), so these must mirror what the endpoint actually exposes.
    Deriving them from ``mcp.list_tools()`` keeps the two in sync automatically.
    """
    tools = await mcp.list_tools()
    return [
        MCPServerTool(
            mcp_server_id=server_id,
            name=tool.name,
            title=getattr(tool, "title", None),
            description=tool.description,
            input_schema=tool.inputSchema,
            is_enabled_by_default=True,
        )
        for tool in tools
    ]


async def build_knowledge_mcp_server(*, token: str, tenant_id: UUID) -> MCPServer:
    """Build the ephemeral MCP server eneo attaches to a completion in tool mode."""
    settings = get_settings()
    server_id = uuid4()
    tools = await _knowledge_tool_entities(server_id)
    return MCPServer(
        id=server_id,
        tenant_id=tenant_id,
        name=KNOWLEDGE_SERVER_NAME,
        description="Loopback server for searching this assistant's knowledge.",
        http_url=(
            f"{settings.internal_mcp_base_url.rstrip('/')}/internal-mcp/knowledge/mcp"
        ),
        http_auth_type="bearer",
        http_auth_config_schema={"token": token},
        is_enabled=True,
        tools=tools,
    )
