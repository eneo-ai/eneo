"""Shared predicate for URL-only file surfacing (signed file references).

A TEXT file is "URL-only" when the assistant has ``inline_file_text`` disabled
and the file's exact original is durably stored (an ORIGINAL content reference
exists) so a signed original-download URL can serve it. Such a file reaches the
model as a signed URL instead of its extracted text, and its derived vision
images are skipped as well.

This predicate must stay identical everywhere it is applied — the completion
send path (assistant_service / context_builder), the preflight token count,
and the attachment-fit guard — or the counted context drifts from the sent
context.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Optional
from uuid import UUID

from eneo.files.file_models import FileType
from eneo.main.config import get_settings

if TYPE_CHECKING:
    from eneo.files.file_models import File
    from eneo.main.config import Settings


def file_reference_base_url(settings: Optional["Settings"] = None) -> str | None:
    """Base URL for signed original-file download links, or None when unset.

    Prefers the explicit tool-facing base URL (reachable server-to-server by an
    MCP tool); falls back to the browser-facing public origin.
    """
    settings = settings or get_settings()
    return settings.file_reference_base_url or settings.public_origin


def url_only_file_ids(files: Iterable["File"], inline_file_text: bool) -> set[UUID]:
    """Ids of TEXT files that reach the model as a signed URL only.

    Empty when inlining is on or no reference base URL is configured. Images
    and audio are never URL-only: the toggle suppresses extracted text, and
    only TEXT files carry it. Files without a stored original (rows predating
    durable originals) always inline so the model still sees them.
    """
    if inline_file_text or not file_reference_base_url():
        return set()
    return {
        file.id
        for file in files
        if file.file_type == FileType.TEXT and file.original_available
    }
