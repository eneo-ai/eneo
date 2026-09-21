"""HTML extraction and link discovery shared by crawler engines."""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup, Tag
from html2text import HTML2Text

from eneo.files.extensions import MIMETYPE_EXTENSIONS_MAPPER
from eneo.websites.domain.source_url import normalize_url as normalize_url

_NOISE_ELEMENTS = (
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "canvas",
    "form",
    "header",
    "nav",
    "footer",
    "aside",
)
_DOCUMENT_SUFFIXES = frozenset(
    {
        ".csv",
        ".docx",
        ".json",
        ".md",
        ".pdf",
        ".pptx",
        ".txt",
        ".xls",
        ".xlsx",
        ".xml",
    }
)
_DOCUMENT_MIME_EXTENSIONS = {
    mime_type: extensions[0]
    for mime_type, extensions in MIMETYPE_EXTENSIONS_MAPPER.items()
    if extensions[0] in _DOCUMENT_SUFFIXES
}
_NON_PAGE_SUFFIXES = frozenset(
    {
        ".7z",
        ".avif",
        ".avi",
        ".bmp",
        ".csv",
        ".css",
        ".docx",
        ".eot",
        ".epub",
        ".flac",
        ".gif",
        ".gz",
        ".ico",
        ".jpeg",
        ".jpg",
        ".js",
        ".m4a",
        ".m4v",
        ".map",
        ".md",
        ".mov",
        ".mp3",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".ogg",
        ".ogv",
        ".otf",
        ".pdf",
        ".png",
        ".pptx",
        ".rar",
        ".svg",
        ".tar",
        ".tif",
        ".tiff",
        ".ttf",
        ".txt",
        ".wav",
        ".webm",
        ".webmanifest",
        ".webp",
        ".woff",
        ".woff2",
        ".xls",
        ".xlsx",
        ".xml",
        ".zip",
    }
)
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    title: str
    content: str
    links: tuple[str, ...]
    file_links: tuple[str, ...]


def is_in_scope(url: str, seed_url: str) -> bool:
    """Match Eneo's existing same-host, path-prefix crawl semantics."""

    if not is_same_origin(url, seed_url, allow_https_upgrade=True):
        return False

    candidate = urlsplit(url)
    seed = urlsplit(seed_url)
    seed_path = seed.path or "/"
    if seed_path == "/":
        return True
    prefix = seed_path.rstrip("/")
    return candidate.path == prefix or candidate.path.startswith(f"{prefix}/")


def is_same_origin(
    url: str, seed_url: str, *, allow_https_upgrade: bool = False
) -> bool:
    """Compare normalized origins; optionally allow only a same-host HTTPS upgrade.

    Normalization removes default ports. Non-default ports must still match.
    Authorization uses the strict default, even when fetching permits an upgrade.
    """
    candidate = urlsplit(url)
    seed = urlsplit(seed_url)
    return (
        (
            candidate.scheme == seed.scheme
            or (
                allow_https_upgrade
                and seed.scheme == "http"
                and candidate.scheme == "https"
            )
        )
        and candidate.hostname == seed.hostname
        and candidate.port == seed.port
    )


def _content_root(soup: BeautifulSoup) -> Tag:
    for element_name in ("main", "article"):
        element = soup.find(element_name)
        if isinstance(element, Tag):
            return element
    role_main = soup.find(role="main")
    if isinstance(role_main, Tag):
        return role_main
    body = soup.find("body")
    if isinstance(body, Tag):
        return body
    return soup


def _url_suffix(url: str) -> str:
    path = unquote(urlsplit(url).path)
    return PurePosixPath(path).suffix.casefold()


def is_page_link(url: str) -> bool:
    """Return whether a URL suffix can represent fetchable page content."""
    return _url_suffix(url) not in _NON_PAGE_SUFFIXES


def is_document_link(url: str) -> bool:
    return _url_suffix(url) in _DOCUMENT_SUFFIXES


def document_extension(content_type: str) -> str | None:
    """Return the extraction suffix for a supported document MIME type."""
    return _DOCUMENT_MIME_EXTENSIONS.get(content_type.lower().split(";", 1)[0].strip())


def extract_html(html: str, url: str) -> ExtractedPage:
    """Extract useful Markdown while retaining links needed for discovery."""

    soup = BeautifulSoup(html, "lxml")
    title_element = soup.find("title")
    title = title_element.get_text(" ", strip=True) if title_element else url

    links: list[str] = []
    file_links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        raw_href = anchor.get("href")
        if not isinstance(raw_href, str):
            continue
        absolute = normalize_url(raw_href, base_url=url)
        if absolute is None:
            continue
        anchor["href"] = absolute
        if absolute in seen:
            continue
        seen.add(absolute)
        if is_document_link(absolute):
            file_links.append(absolute)
        elif is_page_link(absolute):
            links.append(absolute)

    root = _content_root(soup)
    for element in root.find_all(_NOISE_ELEMENTS):
        element.decompose()

    converter = HTML2Text()
    converter.body_width = 0
    converter.ignore_images = True
    converter.ignore_links = False
    converter.protect_links = True
    content = converter.handle(str(root)).strip()
    content = _EXCESS_BLANK_LINES.sub("\n\n", content)

    if title == url:
        heading = root.find("h1")
        if heading:
            title = heading.get_text(" ", strip=True) or url

    return ExtractedPage(
        title=title,
        content=content,
        links=tuple(links),
        file_links=tuple(file_links),
    )
