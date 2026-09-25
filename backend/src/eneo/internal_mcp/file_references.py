"""Resolution of signed file reference URLs inside internal tools.

The prompt lists attached and generated files as signed reference URLs; a
tool that takes one must treat it as a capability handle, not an address:
the token is verified locally and the bytes come from the durable content
store, never from an HTTP fetch. Every internal tool that accepts a reference
resolves it through here so the checks (well-formed reference, valid token,
matching file, matching tenant) cannot drift between tools.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from eneo.authentication.signed_urls import (
    parse_file_reference_url,
    verify_file_original_download_token,
)
from eneo.files.file_content_loader import FileContentLoader
from eneo.files.file_models import File
from eneo.main.exceptions import NotFoundException

logger = logging.getLogger(__name__)

NOT_A_REFERENCE_MESSAGE = (
    'That is not an Eneo attachment URL. Pass the exact "url" value from a '
    "file reference entry, without modifying it."
)
INVALID_LINK_MESSAGE = (
    "The attachment link is invalid or has expired. Ask the user to attach "
    "the file again to get a fresh link."
)
NOT_FOUND_MESSAGE = "No attached file matches that URL."


class FileReferenceRejected(ValueError):
    """A reference url the tool cannot act on; the message is model-facing."""


def verify_reference_url(url: str) -> tuple[UUID, dict[str, Any]]:
    """The file id and verified token payload behind a reference url.

    Cheap and database-free, so tools can reject a malformed or expired
    reference before opening a request-scoped session.
    """
    parsed = parse_file_reference_url(url)
    if parsed is None:
        raise FileReferenceRejected(NOT_A_REFERENCE_MESSAGE)
    file_id, token = parsed
    payload = verify_file_original_download_token(token)
    if payload is None or payload.get("file_id") != str(file_id):
        raise FileReferenceRejected(INVALID_LINK_MESSAGE)
    return file_id, payload


async def load_referenced_file(
    file_id: UUID,
    payload: dict[str, Any],
    tool_ctx: Any,
    *,
    log_tag: str,
) -> File:
    """The byte-complete file behind a verified reference, tenant-checked.

    Missing and inaccessible files are indistinguishable to the caller (no
    existence oracle). Authorization is the signed token plus the tenant
    match; the loader itself projects bytes only.
    """
    try:
        metadata = await tool_ctx.container.file_repo().get_by_id(file_id)
    except NotFoundException:
        logger.info("%s file=%s -> not found", log_tag, file_id)
        raise FileReferenceRejected(NOT_FOUND_MESSAGE) from None
    if (
        payload.get("tenant_id") != str(metadata.tenant_id)
        or metadata.tenant_id != tool_ctx.user.tenant_id
    ):
        logger.info("%s file=%s -> tenant mismatch", log_tag, file_id)
        raise FileReferenceRejected(NOT_FOUND_MESSAGE)
    loader = FileContentLoader(
        repo=tool_ctx.container.file_repo(),
        object_content=tool_ctx.container.object_content_service(),
    )
    return (await loader.load([metadata]))[metadata.id]


async def resolve_reference_file(url: str, tool_ctx: Any, *, log_tag: str) -> File:
    """Verify ``url`` and load the file it references in one step."""
    file_id, payload = verify_reference_url(url)
    return await load_referenced_file(file_id, payload, tool_ctx, log_tag=log_tag)
