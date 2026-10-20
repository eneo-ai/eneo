"""Documents of one imported item, as the space's Documents page reads them."""

from __future__ import annotations

import unicodedata
from typing import Literal, Protocol
from urllib.parse import unquote, urlsplit

SortOrder = Literal["asc", "desc"]


class DocumentSource(Protocol):
    """What the Documents page reads of an item: an entity or its location."""

    @property
    def integration_type(self) -> str: ...

    @property
    def url(self) -> str | None: ...

    @property
    def folder_path(self) -> str | None: ...

    @property
    def resource_type(self) -> str | None: ...


ONEDRIVE_RESOURCE_TYPE = "onedrive"
SHAREPOINT_INTEGRATION_TYPE = "sharepoint"


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


def _folder_path_forms(folder_path: str | None) -> list[list[str]]:
    """The stored folder path's segments: as stored, and decoded once.

    The sync stores the path decoded, so a name like "Budget 50%AB" must not
    be decoded again; a path stored percent-encoded before that still reads
    until the sync refreshes it.
    """
    if not folder_path:
        return []
    stored = [
        unicodedata.normalize("NFC", segment)
        for segment in folder_path.split("/")
        if segment
    ]
    decoded = _segments(folder_path)
    return [stored] if decoded == stored else [stored, decoded]


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
    folder_forms = _folder_path_forms(folder_path)

    anchor = _url_segments(item_url)
    if anchor and _fold(segments[: len(anchor)]) == _fold(anchor):
        rest = folders[len(anchor) :]
        if not folder_forms and resource_type != ONEDRIVE_RESOURCE_TYPE:
            rest = rest[1:]
        return "/".join(rest)

    for folder_segments in folder_forms:
        start = _find(folders, folder_segments)
        if start is not None:
            return "/".join(folders[start + len(folder_segments) :])
    return "/".join(folders)


def document_url_anchor(item: DocumentSource) -> str | None:
    """The item's URL as its document URLs start, for searching below it."""
    return item.url.rstrip("/") or None if item.url else None


def item_relative_path(item: DocumentSource, document_url: str | None) -> str:
    # Confluence pages are not files under an imported folder; their URL path
    # (wiki/spaces/KEY/pages/123) says nothing a user would call a folder.
    if item.integration_type != SHAREPOINT_INTEGRATION_TYPE:
        return ""
    return relative_document_path(
        document_url,
        item_url=item.url,
        folder_path=item.folder_path,
        resource_type=item.resource_type,
    )
