"""Documents of one imported item, as the space's Documents page reads them."""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, Literal
from urllib.parse import unquote, urlsplit

from eneo.integration.presentation.models import (
    IntegrationDocumentItem,
    IntegrationSkippedDocument,
    IntegrationSkippedDocuments,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from eneo.info_blobs.info_blob import InfoBlobInDBNoText
    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from eneo.integration.domain.entities.sync_log import SyncLog

IntegrationDocumentSort = Literal["name", "path", "size", "updated_at"]
SortOrder = Literal["asc", "desc"]

ONEDRIVE_RESOURCE_TYPE = "onedrive"


def _segments(path: str | None) -> list[str]:
    if not path:
        return []
    return [
        unicodedata.normalize("NFC", unquote(segment))
        for segment in path.split("/")
        if segment
    ]


def _url_segments(url: str | None) -> list[str]:
    return _segments(urlsplit(url).path) if url else []


def _fold(segments: list[str]) -> list[str]:
    return [segment.casefold() for segment in segments]


def _find(haystack: list[str], needle: list[str]) -> int | None:
    if not needle:
        return None
    folded_haystack, folded_needle = _fold(haystack), _fold(needle)
    for start in range(len(folded_haystack) - len(folded_needle) + 1):
        if folded_haystack[start : start + len(folded_needle)] == folded_needle:
            return start
    return None


def relative_document_path(
    document_url: str | None,
    *,
    item_url: str | None,
    folder_path: str | None,
    resource_type: str | None,
) -> str:
    """Folders between the imported item and the document; "" when none.

    The item's own web URL (site, drive, folder or file) anchors the match. A
    site URL stops above the document library, so the library segment is the
    drive root and is dropped; a OneDrive URL already names the drive. When a
    document's URL does not share that anchor (the site was renamed, or the
    item was created before URLs were stored) the drive-relative ``folder_path``
    is looked up inside the URL instead, and a document matching neither keeps
    its own folder segments rather than hiding where it came from.
    """
    segments = _url_segments(document_url)
    if not segments:
        return ""
    folders = segments[:-1]
    folder_segments = _segments(folder_path)

    anchor = _url_segments(item_url)
    if anchor and _fold(segments[: len(anchor)]) == _fold(anchor):
        rest = folders[len(anchor) :]
        if not folder_segments and resource_type != ONEDRIVE_RESOURCE_TYPE:
            rest = rest[1:]
        return "/".join(rest)

    start = _find(folders, folder_segments)
    if start is not None:
        return "/".join(folders[start + len(folder_segments) :])
    return "/".join(folders)


def document_items(
    documents: Iterable[InfoBlobInDBNoText], item: IntegrationKnowledge
) -> list[IntegrationDocumentItem]:
    return [
        IntegrationDocumentItem(
            id=document.id,
            title=document.title or document.url or "",
            relative_path=relative_document_path(
                document.url,
                item_url=item.url,
                folder_path=item.folder_path,
                resource_type=item.resource_type,
            ),
            url=document.url or None,
            size=document.size,
            updated_at=document.updated_at or document.created_at,
            source_metadata=document.source_metadata or [],
        )
        for document in documents
    ]


def skipped_documents(sync_log: SyncLog | None) -> IntegrationSkippedDocuments:
    if sync_log is None:
        return IntegrationSkippedDocuments(items=[], total=0, truncated=False)
    metadata = sync_log.metadata
    details = metadata.get("skipped_details", [])
    return IntegrationSkippedDocuments(
        items=[
            IntegrationSkippedDocument(
                file=str(detail.get("file", "")), reason=str(detail.get("reason", ""))
            )
            for detail in details
        ],
        total=int(
            metadata.get("skipped_total", metadata.get("skipped_items", len(details)))
        ),
        truncated=bool(metadata.get("skipped_truncated", False)),
        synced_at=sync_log.completed_at or sync_log.started_at,
    )
