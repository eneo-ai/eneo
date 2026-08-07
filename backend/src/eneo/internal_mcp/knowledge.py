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
from typing import Any, Literal, NamedTuple
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import EmbeddedResource, TextContent, TextResourceContents
from pydantic import AnyUrl

from eneo.info_blobs.info_blob_repo import InfoBlobListing
from eneo.internal_mcp.constants import KNOWLEDGE_SERVER_NAME
from eneo.internal_mcp.foundation import (
    build_ephemeral_server,
    default_page_cap,
    internal_tool_context,
)
from eneo.main.exceptions import NotFoundException
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer

logger = logging.getLogger(__name__)

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

# Overview strategy constants. A source is characterised by its document titles
# (the coverage signal) plus a thin spread of excerpts (the texture); neither
# needs an embedding, which is the point, since a question about what a corpus
# contains has no content query to embed.
OVERVIEW_TITLE_FETCH = 400
OVERVIEW_TITLE_BUDGET_RATIO = 0.55
OVERVIEW_SAMPLE_DOCUMENTS = 12
OVERVIEW_MAX_CHUNKS_PER_DOC = 4
OVERVIEW_EXCERPT_CHARS = 700

# Returned whenever a document id names nothing the assistant can reach. Missing
# and out-of-scope must be indistinguishable, so this is a constant, never
# interpolated with what was asked for.
NOT_FOUND_MESSAGE = "No document with that id in this assistant's knowledge sources."

# The same discipline for the `within` scope argument, which accepts either a
# source id or a document id: one message covers every way it can miss.
SCOPE_NOT_FOUND_MESSAGE = (
    "No knowledge source or document with that id in this assistant's knowledge "
    "sources. Call list_knowledge_sources for the available source_ids."
)

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


class KnowledgeScope(NamedTuple):
    """What a search or overview is allowed to look at.

    The three source fields are named after :class:`Assistant`'s so a scope can
    be handed to ``Datastore.semantic_search`` exactly where the assistant used
    to be, with no branch on which kind of thing narrowed it.
    """

    label: str
    collections: list[Any]
    websites: list[Any]
    integration_knowledge_list: list[Any]
    info_blob_ids: list[UUID]
    source_id: UUID | None = None
    name: str = ""


class _ScopeNotResolved(Exception):
    """Carries the exact text a tool should return instead of searching."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _assistant_scope(assistant) -> KnowledgeScope:
    return KnowledgeScope(
        label="all knowledge sources",
        collections=list(assistant.collections),
        websites=list(assistant.websites),
        integration_knowledge_list=list(assistant.integration_knowledge_list),
        info_blob_ids=[],
    )


def _source_scopes(assistant) -> list[KnowledgeScope]:
    """One single-source scope per knowledge source attached to the assistant."""
    scopes = [
        KnowledgeScope(
            label=f"Collection '{collection.name}'",
            collections=[collection],
            websites=[],
            integration_knowledge_list=[],
            info_blob_ids=[],
            source_id=collection.id,
            name=collection.name,
        )
        for collection in assistant.collections
    ]
    scopes += [
        KnowledgeScope(
            label=f"Website '{website.name or website.url}'",
            collections=[],
            websites=[website],
            integration_knowledge_list=[],
            info_blob_ids=[],
            source_id=website.id,
            name=website.name or website.url,
        )
        for website in assistant.websites
    ]
    scopes += [
        KnowledgeScope(
            label=f"Integration '{knowledge.name}'",
            collections=[],
            websites=[],
            integration_knowledge_list=[knowledge],
            info_blob_ids=[],
            source_id=knowledge.id,
            name=knowledge.name,
        )
        for knowledge in assistant.integration_knowledge_list
    ]
    return scopes


def _matching_sources(assistant, ref: str) -> list[KnowledgeScope]:
    """Sources named by ``ref``, by id or by exact name.

    Membership only: the candidates are the assistant's own attached sources, so
    a foreign or invented id matches nothing and never reaches the database.
    Ids from the three source tables cannot collide, which is what lets one
    argument address all of them without a scope-kind discriminator.

    The name fallback exists because models tend to pass back the name they were
    shown rather than the id beside it. It can only ever match inside the
    assistant's own scope, so it grants no reach.
    """
    candidates = _source_scopes(assistant)
    ref = ref.strip()
    try:
        wanted = UUID(ref)
    except ValueError:
        pass
    else:
        return [scope for scope in candidates if scope.source_id == wanted]

    folded = ref.casefold()
    return [scope for scope in candidates if scope.name.casefold() == folded]


def _ambiguous_source_message(ref: str) -> str:
    """Only names can be ambiguous, and only names the caller was already shown."""
    return (
        f"Several knowledge sources are named '{ref.strip()}'. Use the source_id "
        "from list_knowledge_sources instead of the name."
    )


async def _document_scope(container, assistant, ref: str) -> KnowledgeScope | None:
    """Scope covering one document, when ``ref`` is a document the assistant has."""
    try:
        blob_id = UUID(ref)
    except ValueError:
        return None
    try:
        blob = await container.info_blob_repo().get(blob_id)
    except NotFoundException:
        return None
    if not _blob_in_scope(blob, assistant):
        return None
    return KnowledgeScope(
        label=f"Document '{blob.title or 'Untitled source'}'",
        collections=[],
        websites=[],
        integration_knowledge_list=[],
        info_blob_ids=[blob.id],
        source_id=blob.id,
        name=blob.title or "",
    )


async def _resolve_scope(container, assistant, within: str | None) -> KnowledgeScope:
    """Resolve the ``within`` argument to a scope, or raise with what to say.

    Sources are tried before documents so a source id never costs a database
    round-trip.
    """
    if within is None:
        return _assistant_scope(assistant)

    matches = _matching_sources(assistant, within)
    if len(matches) > 1:
        raise _ScopeNotResolved(_ambiguous_source_message(within))
    if matches:
        return matches[0]

    scope = await _document_scope(container, assistant, within)
    if scope is None:
        raise _ScopeNotResolved(SCOPE_NOT_FOUND_MESSAGE)
    return scope


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


def _chunk_resource(
    *,
    info_blob_id: UUID,
    chunk_no: int,
    title: str,
    text: str,
    meta: dict | None = None,
) -> EmbeddedResource:
    """One chunk as citable content.

    Shared by search hits and overview excerpts so both cite identically. The
    document_id is repeated inside the text because the model never sees the
    resource uri or its ``_meta``.
    """
    return EmbeddedResource(
        type="resource",
        resource=TextResourceContents(
            uri=AnyUrl(f"eneo://info-blob/{info_blob_id}#chunk-{chunk_no}"),
            mimeType="text/plain",
            text=f"Title: {title}\ndocument_id: {info_blob_id}\n\n{text}",
            # `title` is the generic meta key the reference UI reads for the
            # chip label (falls back to the uri host otherwise).
            _meta={"title": title, "info_blob_id": str(info_blob_id), **(meta or {})},
        ),
    )


def _fit_titles(
    listings: Sequence[InfoBlobListing], budget: int
) -> tuple[list[InfoBlobListing], list[str]]:
    """As many title lines as fit the character budget, in order.

    Cut by characters rather than a fixed row count: title lengths vary by an
    order of magnitude, and a fixed page would either waste the budget or force
    a source-heavy collection through many more calls than it needs.
    """
    kept: list[InfoBlobListing] = []
    lines: list[str] = []
    used = 0
    for listing in listings:
        line = f"- {listing.label}  document_id: {listing.id}"
        if used + len(line) + 1 > budget and kept:
            break
        used += len(line) + 1
        kept.append(listing)
        lines.append(line)
    return kept, lines


def _excerpts_per_document(document_count: int) -> int:
    """How many passages to take from each sampled document.

    The excerpt allowance is a budget for the source as a whole, not a
    per-document quota. A source with one document should spend it on several
    passages from that document rather than leave most of it unused, which
    otherwise leaves the model characterising a whole document from whatever
    single passage sits at its midpoint.
    """
    if document_count < 1:
        return 0
    return max(
        1,
        min(OVERVIEW_SAMPLE_DOCUMENTS // document_count, OVERVIEW_MAX_CHUNKS_PER_DOC),
    )


def _sample_targets(
    listings: Sequence[InfoBlobListing], count: int
) -> list[InfoBlobListing]:
    """Up to ``count`` documents spread across the listing, not its first N."""
    if not listings or count < 1:
        return []
    if len(listings) <= count:
        return list(listings)
    # Pick each target at the midpoint of one of ``count`` equal bands. Integer
    # strides collapse to 1 whenever ``count < len(listings) < 2 * count``,
    # which would select the first N documents instead of spanning the list.
    return [
        listings[((2 * index + 1) * len(listings)) // (2 * count)]
        for index in range(count)
    ]


def _search_result_content(query: str, chunks) -> list[TextContent | EmbeddedResource]:
    """Convert search hits to MCP content blocks.

    Each chunk becomes an ``EmbeddedResource`` so the completion layer's
    tool-result reference handling picks it up and the answer can cite it.
    """
    if not chunks:
        return [
            TextContent(
                type="text",
                text=(
                    f"No results for '{query}' in this assistant's knowledge. "
                    "Retry once with different wording; if still nothing, the "
                    "sources do not cover this: switch to another suitable "
                    "tool (for example a web search tool) without asking the "
                    "user first, and say it could not be found only when no "
                    "tool applies."
                ),
            )
        ]

    content: list[TextContent | EmbeddedResource] = [
        TextContent(
            type="text",
            text=f"{len(chunks)} result(s) for '{query}':",
        )
    ]
    for chunk in chunks:
        content.append(
            _chunk_resource(
                info_blob_id=chunk.info_blob_id,
                chunk_no=chunk.chunk_no,
                title=chunk.info_blob_title or "Untitled source",
                text=chunk.text,
                meta={"score": chunk.score},
            )
        )
    return content


def _overview_content(
    *,
    scope: KnowledgeScope,
    total: int,
    offset: int,
    title_lines: Sequence[str],
    excerpts,
    excerpt_titles: dict[UUID, str],
) -> list[TextContent | EmbeddedResource]:
    """One page describing a source: what is in it, plus a taste of the content.

    Titles carry the coverage claim and excerpts only illustrate it, so the
    caveat between them is load-bearing: the excerpts are a thin sample and a
    summary built from them alone would understate the source.
    """
    if total == 0:
        return [
            TextContent(
                type="text",
                text=f"{scope.label} contains no documents.",
            )
        ]
    if not title_lines:
        return [
            TextContent(
                type="text",
                text=(
                    f"Offset {offset} is past the end of {scope.label} "
                    f"({total} documents)."
                ),
            )
        ]

    shown_to = offset + len(title_lines)
    listing_status = (
        " This completes the title listing."
        if shown_to >= total
        else " The title listing is incomplete."
    )
    content: list[TextContent | EmbeddedResource] = [
        TextContent(
            type="text",
            text=(
                f"{scope.label} contains {total} document(s). "
                f"Showing {offset + 1}-{shown_to} by title.{listing_status}\n"
                + "\n".join(title_lines)
            ),
        )
    ]

    if excerpts:
        # Counted by document, not by excerpt: a source with few documents gets
        # several passages from each, and "sampled from 4 documents" would then
        # overstate the coverage if it counted passages.
        sampled_documents = len({excerpt.info_blob_id for excerpt in excerpts})
        content.append(
            TextContent(
                type="text",
                text=(
                    f"{len(excerpts)} excerpt(s) sampled from {sampled_documents} "
                    "of these documents follow. They are a small sample, not the "
                    "whole source: base any statement about what this source "
                    "covers on the document titles returned across all pages."
                ),
            )
        )
        for excerpt in excerpts:
            content.append(
                _chunk_resource(
                    info_blob_id=excerpt.info_blob_id,
                    chunk_no=excerpt.chunk_no,
                    title=excerpt_titles.get(excerpt.info_blob_id, "Untitled source"),
                    text=excerpt.text[:OVERVIEW_EXCERPT_CHARS],
                )
            )

    if shown_to < total:
        content.append(
            TextContent(
                type="text",
                text=(
                    f"Titles truncated at document {shown_to} of {total}. Do not "
                    "answer the source-overview question yet. Call describe_source "
                    f"again with offset={shown_to} for the next part, and continue "
                    "until the title listing is complete."
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
    within: str | None = None,
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

    Optional "within" narrows the search to one knowledge source or one
    document: pass a source_id from list_knowledge_sources, or a document_id
    from an earlier result. Use it to probe one large document instead of
    reading all of it with read_source. Omit it to search everything.

    If nothing relevant returns, retry once with different wording before
    concluding the sources do not cover it; then fall back to another
    suitable tool when one applies. Each result includes a
    document_id; pass it to read_source to read that full document.

    This tool always needs a content query. To answer what a source covers or
    contains, use describe_source; to list the sources themselves, use
    list_knowledge_sources.
    """
    fetch, autocut_cutoff, cap = _resolve_search_params(mode, max_results)
    logger.debug("[RAG] search_knowledge query=%r within=%r", query[:120], within)
    async with internal_tool_context(ctx) as (container, _user, assistant_id):
        assistant, _ = await container.assistant_service().get_assistant(assistant_id)
        # The embedding model comes from the assistant, not the scope: a
        # document scope carries no source to read it from.
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

        try:
            scope = await _resolve_scope(container, assistant, within)
        except _ScopeNotResolved as unresolved:
            logger.info(
                "[RAG] search_knowledge assistant=%s within=%r -> unresolved",
                assistant_id,
                within,
            )
            return [TextContent(type="text", text=unresolved.message)]

        chunks = await container.datastore().semantic_search(
            query,
            embedding_model=embedding_model,
            collections=scope.collections,
            websites=scope.websites,
            integration_knowledge_list=scope.integration_knowledge_list,
            info_blob_ids=scope.info_blob_ids,
            num_chunks=fetch,
            autocut_cutoff=autocut_cutoff,
        )

    fetched = len(chunks)
    if mode == "overview" and not scope.info_blob_ids:
        chunks = _diversify(chunks, per_doc=OVERVIEW_CHUNKS_PER_DOC, cap=cap)
    else:
        chunks = chunks[:cap]
    top_score = f"{chunks[0].score:.3f}" if chunks else "n/a"
    if scope.info_blob_ids:
        # Within one document the model is reading, not ranking: reading order
        # carries more meaning than relevance order.
        chunks = sorted(chunks, key=lambda chunk: chunk.chunk_no)
    logger.info(
        "[RAG] search_knowledge assistant=%s mode=%s scope=%s fetch=%d fetched=%d "
        "returned=%d top_score=%s",
        assistant_id,
        mode,
        scope.label,
        fetch,
        fetched,
        len(chunks),
        top_score,
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
    not_found = TextContent(type="text", text=NOT_FOUND_MESSAGE)
    try:
        blob_id = UUID(document_id)
    except ValueError:
        return [TextContent(type="text", text="Invalid document_id.")]
    offset = max(0, offset)

    async with internal_tool_context(ctx) as (container, _user, assistant_id):
        assistant, _ = await container.assistant_service().get_assistant(assistant_id)
        try:
            blob = await container.info_blob_repo().get(blob_id)
        except NotFoundException:
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


@mcp.tool(title="Describe knowledge source")
async def describe_source(
    ctx: Context,
    source_id: str | None = None,
    offset: int = 0,
) -> list[TextContent | EmbeddedResource]:
    """Survey one knowledge source without a search query: what it contains.

    Use for questions about a source itself rather than about a fact inside
    it ("what does this collection cover?", "summarize this knowledge
    source", "vad avhandlar den här kunskapskällan?"). Searching cannot
    answer those: there is no content query to match, and searching for words
    like "summary" or "content" retrieves whatever happens to use them. Pass
    the source_id shown by list_knowledge_sources, or omit it when the
    assistant has only one source.

    Returns the source's document titles plus short excerpts sampled from
    across its documents. Write the summary yourself from that material, and
    base statements about what the source covers on the complete title list:
    the excerpts are a small sample, not the whole source. Long sources are
    returned in parts; keep calling with the offset from each truncation notice
    and do not answer until the title listing is complete. To go deeper on one
    document, read it with read_source or query it with search_knowledge and
    within=<document_id>.
    """
    offset = max(0, offset)
    async with internal_tool_context(ctx) as (container, _user, assistant_id):
        assistant, _ = await container.assistant_service().get_assistant(assistant_id)
        sources = _source_scopes(assistant)
        if not sources:
            return [
                TextContent(
                    type="text",
                    text="This assistant has no knowledge sources attached.",
                )
            ]

        if source_id is None:
            if len(sources) > 1:
                listing = "\n".join(
                    f"- {scope.label} source_id: {scope.source_id}" for scope in sources
                )
                return [
                    TextContent(
                        type="text",
                        text=(
                            "This assistant has several knowledge sources. Call "
                            "describe_source again with one of these source_ids:\n"
                            + listing
                        ),
                    )
                ]
            scope = sources[0]
        else:
            matches = _matching_sources(assistant, source_id)
            if len(matches) > 1:
                return [
                    TextContent(type="text", text=_ambiguous_source_message(source_id))
                ]
            if not matches:
                return [TextContent(type="text", text=SCOPE_NOT_FOUND_MESSAGE)]
            scope = matches[0]

        source_ids = {
            "group_ids": [collection.id for collection in scope.collections],
            "website_ids": [website.id for website in scope.websites],
            "integration_knowledge_ids": [
                knowledge.id for knowledge in scope.integration_knowledge_list
            ],
        }
        blob_repo = container.info_blob_repo()
        total = await blob_repo.count_by_sources(**source_ids)
        listings = await blob_repo.list_by_sources(
            **source_ids, limit=OVERVIEW_TITLE_FETCH, offset=offset
        )

        kept, title_lines = _fit_titles(
            listings, int(default_page_cap() * OVERVIEW_TITLE_BUDGET_RATIO)
        )
        targets = _sample_targets(kept, OVERVIEW_SAMPLE_DOCUMENTS)
        excerpts = (
            await container.info_blob_chunk_repo().sample_evenly(
                info_blob_ids=[listing.id for listing in targets],
                per_document=_excerpts_per_document(len(targets)),
            )
            if targets
            else []
        )

    logger.info(
        "[RAG] describe_source assistant=%s scope=%s total=%d offset=%d titles=%d "
        "excerpts=%d",
        assistant_id,
        scope.label,
        total,
        offset,
        len(title_lines),
        len(excerpts),
    )
    return _overview_content(
        scope=scope,
        total=total,
        offset=offset,
        title_lines=title_lines,
        excerpts=excerpts,
        excerpt_titles={listing.id: listing.label for listing in targets},
    )


@mcp.tool(title="List knowledge sources")
async def list_knowledge_sources(ctx: Context) -> str:
    """List the knowledge sources attached to this assistant.

    Use this tool whenever the user asks what knowledge, sources or
    documents are available, in preference to similarly named listing
    tools from other servers.

    Each line shows the source's source_id: pass it to describe_source to see
    what that source contains, or as search_knowledge's "within" to search
    only that source.
    """
    async with internal_tool_context(ctx) as (container, _user, assistant_id):
        assistant, _ = await container.assistant_service().get_assistant(assistant_id)

        lines: list[str] = []
        for collection in assistant.collections:
            lines.append(
                f"- Collection '{collection.name}'"
                f" ({collection.num_info_blobs} documents)"
                f" source_id: {collection.id}"
            )
        for website in assistant.websites:
            name = website.name or website.url
            lines.append(f"- Website '{name}' ({website.url}) source_id: {website.id}")
        for knowledge in assistant.integration_knowledge_list:
            lines.append(f"- Integration '{knowledge.name}' source_id: {knowledge.id}")

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
