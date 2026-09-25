"""Shared predicate for URL-only file surfacing (signed file references).

A TEXT file is "URL-only" when a reference base URL is configured, the
assistant has ``inline_file_text`` disabled, and the file's exact original is
durably stored and readable (``File.original_available``) so a signed
original-download URL can serve it. Which store holds the bytes (PostgreSQL
inline or an object store) is the content service's concern: the download
endpoint dispatches to either, so the reference surface never asks. Such a
file reaches the model as a signed URL instead of its extracted text, and its
derived vision images are skipped as well.

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
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.files.file_models import File
    from eneo.main.config import Settings


def file_reference_base_url(settings: Optional["Settings"] = None) -> str | None:
    """Base URL for signed original-file download links, or None when unset.

    Prefers the explicit tool-facing base URL (reachable server-to-server by an
    MCP tool); falls back to the browser-facing public origin.
    """
    settings = settings or get_settings()
    return settings.file_reference_base_url or settings.public_origin


def referenced_file_ids(files: Iterable["File"]) -> set[UUID]:
    """Ids of TEXT files a signed reference URL can actually serve.

    These files get a JSON reference entry in the prompt whatever the
    assistant's inlining mode, so the built-in ``read_file`` consumer attaches
    whenever this set is non-empty. Empty when no reference base URL is
    configured. Images and audio never carry reference URLs, and files
    without a readable stored original (rows predating durable originals, or
    object-store content whose store is no longer connected) only ever
    inline.
    """
    if not file_reference_base_url():
        return set()
    return {
        file.id
        for file in files
        if file.file_type == FileType.TEXT and file.original_available
    }


def image_reference_file_ids(files: Iterable["File"]) -> set[UUID]:
    """Ids of IMAGE files a signed reference URL can serve to an image tool.

    Covers user-attached images (stored original) and generated images (the
    generated artifact is the original). Derived images (rendered document
    pages, embedded images) are excluded: they belong to their parent document
    and are never edit inputs. Uploads without a readable stored original are
    simply not marked available. Images are never URL-only; the reference is
    an extra handle next to the vision input, not a replacement for it.
    """
    if not file_reference_base_url():
        return set()
    return {
        file.id
        for file in files
        if file.file_type == FileType.IMAGE
        and file.original_available
        and file.parent_file_id is None
    }


def reference_url_file_ids(files: Iterable["File"]) -> set[UUID]:
    """Ids of every file that gets a signed reference URL in the prompt."""
    files = list(files)
    return referenced_file_ids(files) | image_reference_file_ids(files)


def inline_file_text_for_model(
    inline_file_text: bool, completion_model: "CompletionModel"
) -> bool:
    """URL-only mode needs a model that can call the files tool.

    A model without tool calling would see only a link it cannot open, so
    the text is inlined after all whatever the assistant or policy says.
    Ask-time and preflight both go through here so the meter and the
    request agree.
    """
    return inline_file_text or not completion_model.supports_tool_calling


def url_only_file_ids(files: Iterable["File"], inline_file_text: bool) -> set[UUID]:
    """Ids of TEXT files that reach the model as a signed URL only.

    Empty when inlining is on or no reference base URL is configured. Images
    and audio are never URL-only: the toggle suppresses extracted text, and
    only TEXT files carry it. Files without a readable stored original (rows
    predating durable originals) always inline so the model still sees them.
    """
    if inline_file_text:
        return set()
    return referenced_file_ids(files)
