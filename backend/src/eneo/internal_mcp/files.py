# pyright: basic
# FastMCP's Context surface is largely untyped; this module is a thin adapter
# over it, so strict unknown-type checking adds noise without safety here.
"""Internal MCP server exposing conversation attachments as a read tool.

Attached text files with a durably stored original reach the model as signed
reference URLs (alongside their inlined text, or instead of it when the
assistant runs with ``inline_file_text`` disabled). This server is the
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
from mcp.types import TextContent

from eneo.authentication.signed_urls import (
    parse_file_reference_url,
    verify_file_original_download_token,
)
from eneo.files.file_content_loader import FileContentLoader
from eneo.files.file_models import FileType
from eneo.internal_mcp.constants import FILES_SERVER_NAME
from eneo.internal_mcp.foundation import (
    build_ephemeral_server,
    default_page_cap,
    internal_tool_context,
)
from eneo.main.exceptions import NotFoundException
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer

logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="Eneo Files",
    stateless_http=True,
    instructions=(
        "Tools for reading files the user attached to this conversation. They "
        "operate only on the signed attachment URLs provided in the "
        "conversation; scope is fixed by the access token."
    ),
)

NOT_A_REFERENCE_MESSAGE = (
    'That is not an Eneo attachment URL. Pass the exact "url" value from an '
    "attached-file reference entry, without modifying it."
)
INVALID_LINK_MESSAGE = (
    "The attachment link is invalid or has expired. Ask the user to attach "
    "the file again to get a fresh link."
)
NOT_FOUND_MESSAGE = "No attached file matches that URL."


def _text(message: str) -> list[TextContent]:
    return [TextContent(type="text", text=message)]


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
) -> list[TextContent]:
    """Read the text content of a file the user attached to this conversation.

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
    task (for example tabular or spreadsheet analysis tools, or tools that
    summarize files too large to read into context), prefer that tool and
    pass it the same url; if it fails or no such tool exists, use this one
    rather than telling the user the file cannot be read.
    """
    parsed = parse_file_reference_url(url)
    if parsed is None:
        return _text(NOT_A_REFERENCE_MESSAGE)
    file_id, token = parsed

    payload = verify_file_original_download_token(token)
    if payload is None or payload.get("file_id") != str(file_id):
        return _text(INVALID_LINK_MESSAGE)

    offset = max(0, offset)
    async with internal_tool_context(ctx) as tool_ctx:
        try:
            metadata = await tool_ctx.container.file_repo().get_by_id(file_id)
        except NotFoundException:
            # Missing and inaccessible must be indistinguishable to the
            # caller (no existence oracle).
            logger.info("[FILES] read_file file=%s -> not found", file_id)
            return _text(NOT_FOUND_MESSAGE)
        if (
            payload.get("tenant_id") != str(metadata.tenant_id)
            or metadata.tenant_id != tool_ctx.user.tenant_id
        ):
            logger.info("[FILES] read_file file=%s -> tenant mismatch", file_id)
            return _text(NOT_FOUND_MESSAGE)
        # Bytes moved to object content; hydrate the extracted text the same
        # way the completion layer does. Authorization happened above: the
        # signed token plus tenant match gates access.
        loader = FileContentLoader(
            repo=tool_ctx.container.file_repo(),
            object_content=tool_ctx.container.object_content_service(),
        )
        file = (await loader.load([metadata]))[metadata.id]

    logger.info(
        "[FILES] read_file file=%s type=%s offset=%d size=%d",
        file_id,
        file.file_type.value,
        offset,
        len(file.text or ""),
    )
    return _file_content(file, offset=offset, page_cap=default_page_cap())


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
        "\n\nEvery file attached to this conversation is readable here, "
        "whatever its reference url looks like."
    )


async def build_files_mcp_server(
    *, token: str, tenant_id: UUID, attachment_labels: Sequence[str] = ()
) -> MCPServer:
    """Build the ephemeral MCP server eneo attaches for referenced attachments."""
    return await build_ephemeral_server(
        mcp,
        name=FILES_SERVER_NAME,
        description="Loopback server for reading files attached to this conversation.",
        token=token,
        tenant_id=tenant_id,
        tool_description_suffixes={"read_file": _attachments_suffix(attachment_labels)}
        if attachment_labels
        else None,
    )
