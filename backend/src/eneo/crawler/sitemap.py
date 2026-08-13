"""Bounded parsing helpers for sitemap indexes and URL sets."""

import gzip
from dataclasses import dataclass
from io import BytesIO
from xml.etree import ElementTree


class InvalidSitemap(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedSitemap:
    kind: str
    locations: tuple[str, ...]


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
        except gzip.BadGzipFile as exc:
            raise InvalidSitemap("invalid gzip sitemap") from exc
        if max_decompressed_bytes is not None and len(body) > max_decompressed_bytes:
            raise InvalidSitemap("decompressed sitemap exceeds size limit")

    lowered_prefix = body[:4096].lower()
    if b"<!doctype" in lowered_prefix or b"<!entity" in lowered_prefix:
        raise InvalidSitemap("DTD and entity declarations are not allowed")

    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise InvalidSitemap("invalid sitemap XML") from exc

    root_name = root.tag.rsplit("}", 1)[-1].lower()
    if root_name not in {"sitemapindex", "urlset"}:
        raise InvalidSitemap(f"unsupported sitemap root: {root_name}")

    locations: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].lower() != "loc":
            continue
        if element.text and element.text.strip():
            locations.append(element.text.strip())
    return ParsedSitemap(kind=root_name, locations=tuple(locations))
