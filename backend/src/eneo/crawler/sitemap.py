"""Bounded parsing helpers for sitemap indexes and URL sets."""

import gzip
import hashlib
from dataclasses import dataclass
from io import BytesIO
from xml.etree import ElementTree


class InvalidSitemap(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedSitemap:
    kind: str
    entries: tuple["SitemapEntry", ...]

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


def snapshot_sitemap(entries: list[SitemapEntry]) -> SitemapSnapshot | None:
    if not entries or any(entry.last_modified is None for entry in entries):
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

    root_name = root.tag.rsplit("}", 1)[-1].lower()
    if root_name not in {"sitemapindex", "urlset"}:
        raise InvalidSitemap(f"unsupported sitemap root: {root_name}")

    entries: list[SitemapEntry] = []
    item_name = "sitemap" if root_name == "sitemapindex" else "url"
    for item in root:
        if item.tag.rsplit("}", 1)[-1].lower() != item_name:
            continue
        location: str | None = None
        last_modified: str | None = None
        for child in item:
            child_name = child.tag.rsplit("}", 1)[-1].lower()
            text = child.text.strip() if child.text else None
            if child_name == "loc":
                location = text
            elif child_name == "lastmod":
                last_modified = text
        if location:
            entries.append(SitemapEntry(location=location, last_modified=last_modified))
    return ParsedSitemap(kind=root_name, entries=tuple(entries))
