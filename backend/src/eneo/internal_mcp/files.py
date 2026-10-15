# pyright: basic
# FastMCP's Context surface is largely untyped; this module is a thin adapter
# over it, so strict unknown-type checking adds noise without safety here.
"""Internal MCP server exposing attachments as a read tool.

Attached text files with a durably stored original reach the model as signed
reference URLs (alongside their inlined text, or instead of it when the
assistant runs with ``inline_file_text`` disabled). Persistent assistant
attachments marked "open with tool" arrive the same way, URL-only. This server is the
built-in consumer of those URLs: ``read_file`` verifies the signed token and
returns the file's already-extracted text, paged. The URL is a capability
handle, not a fetch instruction: content is served through the durable
object-content store, never fetched over HTTP.

See :mod:`eneo.internal_mcp.foundation` for the hosting and authentication
model shared by all internal servers.
"""

from __future__ import annotations

import logging
from typing import Sequence
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent

from eneo.completion_models.application.map_reduce import DigestItem
from eneo.files.file_models import FileType
from eneo.files.tabular_index import TABULAR_INDEX_MAX_CHARS
from eneo.integration.infrastructure.content_service.originals import (
    retain_original_bytes,
)
from eneo.internal_mcp.constants import FILES_SERVER_NAME
from eneo.internal_mcp.digest import (
    DigestRefused,
    SetAside,
    clip_title,
    digest_meta,
    disconnect_check,
    format_digest,
    log_digest,
    plan_or_refuse,
    prepare_digest_model,
    progress_reporter,
    run_bounded_digest,
    validate_instruction,
)
from eneo.internal_mcp.file_references import (
    INVALID_LINK_MESSAGE,
    NOT_A_REFERENCE_MESSAGE,
    NOT_FOUND_MESSAGE,
    FileReferenceRejected,
    load_referenced_file,
    verify_reference_url,
)
from eneo.internal_mcp.foundation import (
    bearer_from_ctx,
    build_ephemeral_server,
    default_page_cap,
    digest_claims_from_token,
    internal_tool_context,
    table_tools_from_token,
)
from eneo.main.config import get_settings
from eneo.mcp_servers.domain.entities.mcp_server import (
    CSV_MIME_TYPE,
    XLSX_MIME_TYPE,
    MCPServer,
)

logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="Eneo Files",
    stateless_http=True,
    instructions=(
        "Tools for reading files attached to this conversation or to this "
        "assistant. They operate only on the signed attachment URLs provided "
        "in the conversation; scope is fixed by the access token."
    ),
)

__all__ = [
    "INVALID_LINK_MESSAGE",
    "NOT_A_REFERENCE_MESSAGE",
    "NOT_FOUND_MESSAGE",
    "build_files_mcp_server",
    "digest_files",
    "mcp",
    "read_file",
]

DIGEST_FITS_ONE_READ_MESSAGE = (
    "That file fits one read: call read_file with its url instead."
)
DIGEST_NARROW_HINT = "Pass fewer files per call, or digest the largest file on its own."


# Files the table tools read whole: when they are attached, read_file points at
# them instead of paging the extracted text into context.
TABULAR_MIME_TYPES = frozenset(
    {CSV_MIME_TYPE, "text/tab-separated-values", XLSX_MIME_TYPE}
)


def _text(message: str) -> list[TextContent]:
    return [TextContent(type="text", text=message)]


def _table_tools_offered(ctx: Context) -> bool:
    """Whether this completion attached inspect_table and query_table."""
    try:
        return table_tools_from_token(bearer_from_ctx(ctx))
    except Exception:  # noqa: BLE001 - no header or claim means no table tools
        return False


def _table_tools_redirect(file) -> list[TextContent]:
    return _text(
        f"'{file.name}' ({file.mimetype}) is a table. Use inspect_table with the "
        "same url to see its sheets, columns, types and sample rows, and "
        "query_table to answer from its rows; both read the file itself. Call "
        "read_file again with raw=true only if those tools could not read it."
    )


def _file_content(file, *, offset: int, page_cap: int) -> list[TextContent]:
    """One page of an attached file's extracted text, with a resume notice.

    Self-capped like the knowledge server's read_source: the proxy's output
    truncation is destructive, so oversized files must be sliced here and
    continued via ``offset``.
    """
    if file.file_type == FileType.IMAGE:
        return _text(
            f"'{file.name}' is an image ({file.mimetype}); it has no text to "
            "read. Vision-capable models receive the image directly."
        )
    if file.file_type == FileType.AUDIO:
        return _text(
            f"'{file.name}' is an audio file ({file.mimetype}); its "
            "transcription, when available, is already part of the "
            "conversation."
        )
    if not file.text:
        return _text(f"No extracted text is available for '{file.name}'.")

    total = len(file.text)
    page = file.text[offset : offset + page_cap]
    if not page:
        return _text(
            f"Offset {offset} is past the end of the file ({total} characters)."
        )

    content = _text(f"File: {file.name} ({file.mimetype})\n\n{page}")
    end = offset + len(page)
    if end < total:
        content.append(
            TextContent(
                type="text",
                text=(
                    f"File truncated at character {end} of {total}. Call "
                    f"read_file again with the same url and offset={end} for "
                    "the next part."
                ),
            )
        )
    return content


@mcp.tool(title="Read attached file")
async def read_file(
    url: str,
    ctx: Context,
    offset: int = 0,
    raw: bool = False,
) -> list[TextContent]:
    """Read the text content of a file attached to this conversation or assistant.

    Pass the exact "url" value from an attached-file reference entry (the
    JSON lines listing filename, mimetype, size_bytes and url); never
    construct or modify URLs. Every reference url is valid input here no
    matter what host or scheme it shows: the url is a signed handle this
    tool verifies, not an address it fetches, so never conclude from the
    url's appearance that an attached file cannot be read. Long files are
    returned in parts; the truncation notice gives the offset for the next
    part.

    This is a general-purpose fallback that loads the file's raw text into
    context. If another available tool is better suited to the file or the
    task (for example tabular or spreadsheet analysis tools, or digest_files
    for a summary, comparison or extraction over a file too large to read in
    a few pages or over several files at once), prefer that tool and pass it
    the same url; if it fails or no such tool exists, use this one rather
    than telling the user the file cannot be read. For a CSV, TSV or Excel
    file, inspect_table and query_table, when available, describe and query
    the file far better than its raw text, also when the user only asks what
    the file contains; while they are available this tool points such a file
    at them instead of returning its text. Set raw=true only when they could
    not read the file: the extracted text is then returned as for any other
    file.
    """
    try:
        file_id, payload = verify_reference_url(url)
    except FileReferenceRejected as exc:
        return _text(str(exc))

    offset = max(0, offset)
    async with internal_tool_context(ctx) as tool_ctx:
        try:
            file = await load_referenced_file(
                file_id, payload, tool_ctx, log_tag="[FILES] read_file"
            )
        except FileReferenceRejected as exc:
            return _text(str(exc))

    if not raw and file.mimetype in TABULAR_MIME_TYPES and _table_tools_offered(ctx):
        logger.info("[FILES] read_file file=%s pointed at the table tools", file_id)
        return _table_tools_redirect(file)

    logger.info(
        "[FILES] read_file file=%s type=%s offset=%d size=%d",
        file_id,
        file.file_type.value,
        offset,
        len(file.text or ""),
    )
    return _file_content(file, offset=offset, page_cap=default_page_cap())


_TABLE_TOOLS_SUFFIX = (
    "\n\nAttached CSV, TSV and Excel files belong to inspect_table and "
    "query_table, which read the file itself; for such a file this tool points "
    "at them instead of returning its text, unless raw=true."
)


def _refusal(message: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=message)])


def _large_table(file) -> bool:
    """A spreadsheet or delimited file whose rows would eat the digest."""
    return retain_original_bytes(file.name, file.mimetype) and (
        len(file.text or "") > TABULAR_INDEX_MAX_CHARS
    )


@mcp.tool(title="Digest attached files")
async def digest_files(
    instruction: str,
    urls: list[str],
    ctx: Context,
) -> CallToolResult:
    """Read attached files in full and answer an instruction across them.

    Use this for a summary, comparison, timeline or extraction over several
    attached files at once, or over one file too large to read in a few
    read_file pages (the entries' size_bytes show which files are large).
    Pass the exact "url" values from the attached-file reference entries;
    never construct or modify them. It is an exhaustive pass: every file is
    read in full, so give a precise instruction and call it once.

    Cost: one model call per text segment plus the merges, up to several
    minutes. The result starts with the files read ([D1], [D2], ...) and a
    coverage line; relay the body faithfully, state the coverage line when
    it is partial, and pass the body unchanged to a document tool when a
    document is wanted. Numbers in CSV or XLSX files belong to the table
    tools: large tables are not digested and are listed with their url for
    those tools. A file that fits one read is refused: use read_file.
    """
    try:
        instruction = validate_instruction(instruction)
    except DigestRefused as refused:
        return _refusal(refused.message)
    wanted = list(dict.fromkeys(url for url in urls if url))
    if not wanted:
        return _refusal("Pass at least one attached-file url.")
    if len(wanted) > get_settings().attachment_max_files:
        return _refusal(
            f"At most {get_settings().attachment_max_files} files per digest."
        )
    verified: list[tuple[UUID, dict]] = []
    for url in wanted:
        try:
            verified.append(verify_reference_url(url))
        except FileReferenceRejected as exc:
            return _refusal(str(exc))
    claims = digest_claims_from_token(bearer_from_ctx(ctx))
    should_stop = disconnect_check(ctx)

    async with internal_tool_context(ctx) as tool_ctx:
        container = tool_ctx.container
        assistant, _ = await container.assistant_service().get_assistant(
            tool_ctx.assistant_id
        )
        try:
            digest_model = await prepare_digest_model(
                tool_ctx, assistant, claims, instruction=instruction
            )
        except DigestRefused as refused:
            return _refusal(refused.message)
        files = []
        for (file_id, payload), url in zip(verified, wanted):
            try:
                file = await load_referenced_file(
                    file_id, payload, tool_ctx, log_tag="[FILES] digest_files"
                )
            except FileReferenceRejected as exc:
                return _refusal(str(exc))
            files.append((file, url))

        items: list[DigestItem] = []
        set_aside: list[SetAside] = []
        for file, url in files:
            title = clip_title(file.name)
            if file.file_type == FileType.IMAGE:
                set_aside.append(SetAside(title, "image; no text to digest"))
            elif file.file_type == FileType.AUDIO:
                set_aside.append(
                    SetAside(title, "audio; its transcription is in the conversation")
                )
            elif not (file.text or "").strip():
                set_aside.append(SetAside(title, "no extracted text"))
            elif _large_table(file):
                set_aside.append(
                    SetAside(title, f"table; use the table tools with url {url}")
                )
            else:
                items.append(
                    DigestItem(key=f"D{len(items) + 1}", title=title, text=file.text)
                )
        if (
            len(files) == 1
            and len(items) == 1
            and len(items[0].text) <= default_page_cap()
        ):
            return _refusal(DIGEST_FITS_ONE_READ_MESSAGE)
        try:
            plan = plan_or_refuse(items, digest_model, narrow_hint=DIGEST_NARROW_HINT)
        except DigestRefused as refused:
            return _refusal(refused.message)

    if not items:
        header = "\n".join(
            [
                "Digest: no readable text among the files.",
                "Not digested (tables):",
                *(f"- {entry.title}: {entry.reason}" for entry in set_aside),
            ]
        )
        return _refusal(header)

    result, seconds = await run_bounded_digest(
        plan,
        digest_model,
        instruction=instruction,
        should_stop=should_stop,
        on_progress=progress_reporter(ctx),
    )
    content = format_digest(
        heading=f"Digest of {len(items)} attached files with {digest_model.models_label}.",
        items=items,
        result=result,
        set_aside=set_aside,
        omitted=0,
        stubs=(),
        body_cap=digest_model.body_cap_chars,
        item_word="files",
    )
    log_digest(
        "[FILES]",
        assistant_id=tool_ctx.assistant_id,
        scope=f"{len(files)} files",
        result=result,
        digest_model=digest_model,
        seconds=seconds,
    )
    return CallToolResult(content=content, _meta=digest_meta(result, digest_model))


def _attachments_suffix(attachment_labels: Sequence[str]) -> str:
    """Static suffix appended when the conversation has referenced attachments.

    Attachment names never enter the description: it is a trusted provider
    channel, and a filename written as a directive would ride it into the
    model as instructions. The JSON reference entries in the conversation
    already name every file, so the suffix only binds the tool to their
    existence.
    """
    if not attachment_labels:
        return ""
    return (
        "\n\nEvery file attached to this conversation or to this assistant is "
        "readable here, whatever its reference url looks like. Files too "
        "large to read in a few pages are reachable through digest_files."
    )


async def build_files_mcp_server(
    *,
    token: str,
    tenant_id: UUID,
    attachment_labels: Sequence[str] = (),
    table_tools: bool = False,
) -> MCPServer:
    """Build the ephemeral MCP server eneo attaches for referenced attachments.

    ``table_tools`` says the completion also attached the file-analysis tools;
    the token must then carry the same claim for read_file to act on it.
    """
    attachments = _attachments_suffix(attachment_labels)
    suffixes: dict[str, str] = {}
    if attachments or table_tools:
        suffixes["read_file"] = attachments + (
            _TABLE_TOOLS_SUFFIX if table_tools else ""
        )
    if attachments:
        suffixes["digest_files"] = attachments
    return await build_ephemeral_server(
        mcp,
        name=FILES_SERVER_NAME,
        description="Loopback server for reading files attached to this conversation.",
        token=token,
        tenant_id=tenant_id,
        tool_description_suffixes=suffixes or None,
    )
