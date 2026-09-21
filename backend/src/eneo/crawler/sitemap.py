"""Bounded parsing helpers for sitemap indexes and URL sets."""

import gzip
import hashlib
from dataclasses import dataclass
from io import BytesIO
from xml.etree import ElementTree

_SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"


class InvalidSitemap(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedSitemap:
    kind: str
    entries: tuple["SitemapEntry", ...]
    structurally_complete: bool

    @property
    def locations(self) -> tuple[str, ...]:
        return tuple(entry.location for entry in self.entries)


@dataclass(frozen=True, slots=True)
class SitemapEntry:
    location: str
    last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class SitemapSnapshot:
    fingerprint: str
    entry_count: int


def _qualified_name(tag: str) -> tuple[str | None, str]:
    if tag.startswith("{"):
        namespace, separator, name = tag[1:].partition("}")
        if separator:
            return namespace, name.lower()
    return None, tag.lower()


def snapshot_sitemap(entries: list[SitemapEntry]) -> SitemapSnapshot | None:
    if any(entry.last_modified is None for entry in entries):
        return None
    canonical = "\n".join(
        f"{entry.location}\t{entry.last_modified}"
        for entry in sorted(entries, key=lambda item: item.location)
    )
    return SitemapSnapshot(
        fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        entry_count=len(entries),
    )


def parse_sitemap(
    body: bytes, *, max_decompressed_bytes: int | None = None
) -> ParsedSitemap:
    if body.startswith(b"\x1f\x8b"):
        try:
            with gzip.GzipFile(fileobj=BytesIO(body)) as compressed:
                body = compressed.read(
                    None
                    if max_decompressed_bytes is None
                    else max_decompressed_bytes + 1
                )
        except (gzip.BadGzipFile, EOFError, OSError) as exc:
            raise InvalidSitemap("invalid gzip sitemap") from exc
        if max_decompressed_bytes is not None and len(body) > max_decompressed_bytes:
            raise InvalidSitemap("decompressed sitemap exceeds size limit")

    # ElementTree expands declared internal entities. Scan the complete bounded
    # document rather than a prefix so declarations cannot be hidden behind a
    # long comment or whitespace preamble.
    lowered_body = body.lower()
    if b"\x00" in body:
        raise InvalidSitemap("sitemaps must use an ASCII-compatible encoding")
    if b"<!doctype" in lowered_body or b"<!entity" in lowered_body:
        raise InvalidSitemap("DTD and entity declarations are not allowed")

    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise InvalidSitemap("invalid sitemap XML") from exc

    root_namespace, root_name = _qualified_name(root.tag)
    if root_name not in {"sitemapindex", "urlset"}:
        raise InvalidSitemap(f"unsupported sitemap root: {root_name}")

    entries: list[SitemapEntry] = []
    item_name = "sitemap" if root_name == "sitemapindex" else "url"
    allowed_fields = (
        {"loc", "lastmod"}
        if root_name == "sitemapindex"
        else {"loc", "lastmod", "changefreq", "priority"}
    )
    # Unknown sitemap dialects remain crawlable, but only the protocol namespace
    # (and the existing no-namespace compatibility form) may authorize cleanup.
    structurally_complete = root_namespace in {None, _SITEMAP_NAMESPACE}
    if root.text and root.text.strip():
        structurally_complete = False
    if any(
        _qualified_name(attribute)[0] in {None, root_namespace}
        for attribute in root.attrib
    ):
        structurally_complete = False
    for item in root:
        item_namespace, parsed_item_name = _qualified_name(item.tag)
        if item.tail and item.tail.strip():
            structurally_complete = False
        if parsed_item_name != item_name or item_namespace != root_namespace:
            structurally_complete = False
            continue
        if item.text and item.text.strip():
            structurally_complete = False
        if any(
            _qualified_name(attribute)[0] in {None, root_namespace}
            for attribute in item.attrib
        ):
            structurally_complete = False
        location: str | None = None
        last_modified: str | None = None
        seen_fields: set[str] = set()
        for child in item:
            child_namespace, child_name = _qualified_name(child.tag)
            if child.tail and child.tail.strip():
                structurally_complete = False
            if child_namespace != root_namespace:
                continue
            if child_name not in allowed_fields:
                structurally_complete = False
                continue
            if child_name in seen_fields:
                structurally_complete = False
            seen_fields.add(child_name)
            if len(child) or any(
                _qualified_name(attribute)[0] in {None, root_namespace}
                for attribute in child.attrib
            ):
                structurally_complete = False
            text = child.text.strip() if child.text else None
            if child_name == "loc":
                location = text
            elif child_name == "lastmod":
                last_modified = text
        if not location:
            structurally_complete = False
            continue
        entries.append(SitemapEntry(location=location, last_modified=last_modified))
    return ParsedSitemap(
        kind=root_name,
        entries=tuple(entries),
        structurally_complete=structurally_complete,
    )
