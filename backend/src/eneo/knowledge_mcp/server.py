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
from typing import Literal
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

# Mode strategy constants. "specific" fetches a small candidate set and lets
# the score-curve elbow cut (autocut) trim the irrelevant tail; "overview"
# over-fetches and then spreads results across documents so a broad question
# sees the corpus, not one document's every chunk.
SPECIFIC_FETCH = 10
SPECIFIC_AUTOCUT = 2
SPECIFIC_CAP = 6
OVERVIEW_FETCH = 60
OVERVIEW_CAP = 15
OVERVIEW_CHUNKS_PER_DOC = 2

mcp = FastMCP(
    name="Eneo Knowledge",
    stateless_http=True,
    instructions=(
        "Search tools for this Eneo assistant's knowledge sources. Scope is "
        "fixed by the access token; tools take no assistant id. Search before "
        "answering, ground answers only in returned sources, and say so when "
        "the sources do not contain the answer."
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


def _resolve_search_params(
    mode: str, max_results: int | None
) -> tuple[int, int | None, int]:
    """Map a search mode to ``(fetch, autocut_cutoff, return_cap)``.

    An explicit ``max_results`` overrides the mode's return cap (still
    ceiling-clamped); the fetch size grows with it so the cap can be met.
    """
    if mode == "overview":
        cap = OVERVIEW_CAP if max_results is None else _clamp_max_results(max_results)
        return OVERVIEW_FETCH, None, cap

    cap = SPECIFIC_CAP if max_results is None else _clamp_max_results(max_results)
    return max(SPECIFIC_FETCH, cap), SPECIFIC_AUTOCUT, cap


def _diversify(chunks, per_doc: int, cap: int):
    """Spread score-ordered chunks across documents, coverage before depth.

    Pass 1 takes each document's best chunk in score order, pass 2 the second
    best, and so on up to ``per_doc``; stops at ``cap`` results.
    """
    by_doc: dict = {}
    for chunk in chunks:
        by_doc.setdefault(chunk.info_blob_id, []).append(chunk)

    selected = []
    for round_no in range(per_doc):
        for doc_chunks in by_doc.values():
            if len(selected) >= cap:
                return selected
            if round_no < len(doc_chunks):
                selected.append(doc_chunks[round_no])
    return selected


def _document_page_content(
    blob, *, offset: int, page_cap: int
) -> list[TextContent | EmbeddedResource]:
    """One page of a document as citable content, with a resume notice.

    The page is self-capped: the proxy's output truncation is destructive
    (the whole result becomes an error blob), so oversized documents must be
    sliced here and continued via ``offset``.
    """
    total = len(blob.text)
    page = blob.text[offset : offset + page_cap]
    if not page:
        return [
            TextContent(
                type="text",
                text=(
                    f"Offset {offset} is past the end of the document "
                    f"({total} characters)."
                ),
            )
        ]

    title = blob.title or "Untitled source"
    content: list[TextContent | EmbeddedResource] = [
        EmbeddedResource(
            type="resource",
            resource=TextResourceContents(
                uri=AnyUrl(f"eneo://info-blob/{blob.id}"),
                mimeType="text/plain",
                text=f"Title: {title}\ndocument_id: {blob.id}\n\n{page}",
                _meta={"info_blob_id": str(blob.id), "offset": offset},
            ),
        )
    ]
    end = offset + len(page)
    if end < total:
        content.append(
            TextContent(
                type="text",
                text=(
                    f"Document truncated at character {end} of {total}. Call "
                    f"read_source again with offset={end} for the next part."
                ),
            )
        )
    return content


def _blob_in_scope(blob, assistant) -> bool:
    """True when the info blob belongs to one of the assistant's sources."""
    return (
        (
            blob.group_id is not None
            and blob.group_id in {c.id for c in assistant.collections}
        )
        or (
            blob.website_id is not None
            and blob.website_id in {w.id for w in assistant.websites}
        )
        or (
            blob.integration_knowledge_id is not None
            and blob.integration_knowledge_id
            in {k.id for k in assistant.integration_knowledge_list}
        )
    )


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
                    text=(
                        f"Title: {title}\n"
                        f"document_id: {chunk.info_blob_id}\n\n"
                        f"{chunk.text}"
                    ),
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
    mode: Literal["specific", "overview"] = "specific",
    max_results: int | None = None,
) -> list[TextContent | EmbeddedResource]:
    """Search this assistant's knowledge sources for relevant passages.

    Write a focused, self-contained query in the language of the sources.
    Modes:
    - "specific" (default): small, high-precision result set for factual
      questions ("when does department X open today?").
    - "overview": results spread across many documents for broad questions
      ("explain X"). For multi-topic questions, make one overview call per
      topic, in parallel.

    If nothing relevant returns, retry once with different wording before
    concluding the sources do not cover it. Each result includes a
    document_id; pass it to read_source to read that full document.
    """
    fetch, autocut_cutoff, cap = _resolve_search_params(mode, max_results)
    logger.debug("[RAG] search_knowledge query=%r", query[:120])
    async with _knowledge_context(ctx) as (container, assistant_id):
        assistant, _ = await container.assistant_service().get_assistant(assistant_id)
        embedding_model = _pick_embedding_model(assistant)
        if embedding_model is None:
            logger.warning(
                "[RAG] search_knowledge called but assistant %s has no "
                "knowledge sources",
                assistant_id,
            )
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
            num_chunks=fetch,
            autocut_cutoff=autocut_cutoff,
        )

    fetched = len(chunks)
    if mode == "overview":
        chunks = _diversify(chunks, per_doc=OVERVIEW_CHUNKS_PER_DOC, cap=cap)
    else:
        chunks = chunks[:cap]
    logger.info(
        "[RAG] search_knowledge assistant=%s mode=%s fetch=%d fetched=%d "
        "returned=%d top_score=%s",
        assistant_id,
        mode,
        fetch,
        fetched,
        len(chunks),
        f"{chunks[0].score:.3f}" if chunks else "n/a",
    )

    return _search_result_content(query, chunks)


@mcp.tool(title="Read source document")
async def read_source(
    document_id: str,
    ctx: Context,
    offset: int = 0,
) -> list[TextContent | EmbeddedResource]:
    """Read the full text of one document from the knowledge sources.

    Use after search_knowledge when chunks are not enough (procedures,
    tables, full policies): pass the document_id shown in a search result.
    Long documents are returned in parts; the truncation notice gives the
    offset for the next part.
    """
    not_found = TextContent(
        type="text",
        text="No document with that id in this assistant's knowledge sources.",
    )
    try:
        blob_id = UUID(document_id)
    except ValueError:
        return [TextContent(type="text", text="Invalid document_id.")]
    offset = max(0, offset)

    async with _knowledge_context(ctx) as (container, assistant_id):
        assistant, _ = await container.assistant_service().get_assistant(assistant_id)
        try:
            blob = await container.info_blob_repo().get(blob_id)
        except Exception:
            # The repo raises on a missing row; out-of-scope and missing must
            # be indistinguishable to the caller (no existence oracle).
            logger.info(
                "[RAG] read_source assistant=%s document=%s -> not found",
                assistant_id,
                blob_id,
            )
            return [not_found]
        if not _blob_in_scope(blob, assistant):
            logger.info(
                "[RAG] read_source assistant=%s document=%s -> out of scope",
                assistant_id,
                blob_id,
            )
            return [not_found]

    page_cap = min(20_000, get_settings().mcp_tool_output_max_chars // 2)
    logger.info(
        "[RAG] read_source assistant=%s document=%s offset=%d size=%d",
        assistant_id,
        blob_id,
        offset,
        len(blob.text),
    )
    return _document_page_content(blob, offset=offset, page_cap=page_cap)


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
