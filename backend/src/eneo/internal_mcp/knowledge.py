# pyright: basic
# FastMCP's Context surface is largely untyped; this module is a thin adapter
# over it, so strict unknown-type checking adds noise without safety here.
"""Internal MCP server exposing knowledge search as on-demand tools.

The bearer token's ``assistant_id`` claim fixes whose knowledge may be
searched; see :mod:`eneo.internal_mcp.foundation` for the hosting and
authentication model shared by all internal servers.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import EmbeddedResource, TextContent, TextResourceContents
from pydantic import AnyUrl

from eneo.internal_mcp.foundation import (
    build_ephemeral_server,
    default_page_cap,
    internal_tool_context,
)
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer

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

# Most source labels named in the search tool's description; the rest collapse
# to "and N more" so source-heavy assistants do not bloat every completion's
# tool schema.
DESCRIPTION_SOURCES_CAP = 10

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
                _meta={
                    "title": title,
                    "info_blob_id": str(blob.id),
                    "offset": offset,
                },
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
                    # `title` is the generic meta key the reference UI reads
                    # for the chip label (falls back to the uri host otherwise).
                    _meta={
                        "title": title,
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

    Write the query as a focused, self-contained natural-language phrase in
    the language of the sources (e.g. "opening hours recycling center", not
    "opening_hours_recycling_center" or a bag of keywords). Semantic search
    matches meaning, so phrase it the way the sources would.
    Modes:
    - "specific" (default): small, high-precision result set for factual
      questions ("when does department X open today?").
    - "overview": results spread across many documents for broad questions
      ("explain X"). For multi-topic questions, make one overview call per
      topic, in parallel.

    If nothing relevant returns, retry once with different wording before
    concluding the sources do not cover it. Each result includes a
    document_id; pass it to read_source to read that full document. For
    meta-questions about what knowledge is available, use
    list_knowledge_sources instead of searching.
    """
    fetch, autocut_cutoff, cap = _resolve_search_params(mode, max_results)
    logger.debug("[RAG] search_knowledge query=%r", query[:120])
    async with internal_tool_context(ctx) as (container, _user, assistant_id):
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

    async with internal_tool_context(ctx) as (container, _user, assistant_id):
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

    logger.info(
        "[RAG] read_source assistant=%s document=%s offset=%d size=%d",
        assistant_id,
        blob_id,
        offset,
        len(blob.text),
    )
    return _document_page_content(blob, offset=offset, page_cap=default_page_cap())


@mcp.tool(title="List knowledge sources")
async def list_knowledge_sources(ctx: Context) -> str:
    """List the knowledge sources attached to this assistant.

    Use this tool whenever the user asks what knowledge, sources or
    documents are available, in preference to similarly named listing
    tools from other servers.
    """
    async with internal_tool_context(ctx) as (container, _user, assistant_id):
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
# Ephemeral-server builder
# --------------------------------------------------------------------------- #
def _sources_suffix(source_labels: Sequence[str]) -> str:
    """Per-assistant coverage note appended to the search tool description.

    Naming the sources inside the description is what lets the model pick this
    tool over similarly named tools from other MCP servers.
    """
    if not source_labels:
        return ""
    shown = list(source_labels[:DESCRIPTION_SOURCES_CAP])
    listing = "; ".join(shown)
    remaining = len(source_labels) - len(shown)
    if remaining > 0:
        listing += f"; and {remaining} more"
    return (
        f"\n\nCovers these knowledge sources: {listing}. Content questions "
        "about any of these MUST be answered with this tool, not with "
        "similarly named tools from other servers."
    )


async def build_knowledge_mcp_server(
    *, token: str, tenant_id: UUID, source_labels: Sequence[str] = ()
) -> MCPServer:
    """Build the ephemeral MCP server eneo attaches to a completion in tool mode."""
    return await build_ephemeral_server(
        mcp,
        name=KNOWLEDGE_SERVER_NAME,
        description="Loopback server for searching this assistant's knowledge.",
        token=token,
        tenant_id=tenant_id,
        tool_description_suffixes={"search_knowledge": _sources_suffix(source_labels)}
        if source_labels
        else None,
    )
