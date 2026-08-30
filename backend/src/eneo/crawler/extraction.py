"""HTML extraction and link discovery shared by crawler engines."""

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag
from html2text import HTML2Text

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
    {".csv", ".docx", ".json", ".md", ".pdf", ".pptx", ".txt", ".xls", ".xlsx", ".xml"}
)
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    title: str
    content: str
    links: tuple[str, ...]
    file_links: tuple[str, ...]


def normalize_url(url: str, *, base_url: str | None = None) -> str | None:
    """Return a stable HTTP URL identity, or None for unsupported links."""

    absolute = urljoin(base_url, url) if base_url else url
    try:
        parsed = urlsplit(absolute)
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname
    if scheme not in {"http", "https"} or not hostname:
        return None

    host = hostname.lower()
    if port and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    path = parsed.path or "/"
    return urlunsplit((scheme, host, path, parsed.query, ""))


def is_in_scope(url: str, seed_url: str) -> bool:
    """Match Eneo's existing same-host, path-prefix crawl semantics."""

    candidate = urlsplit(url)
    seed = urlsplit(seed_url)
    if candidate.hostname != seed.hostname or candidate.port != seed.port:
        return False

    seed_path = seed.path or "/"
    if seed_path == "/":
        return True
    prefix = seed_path.rstrip("/")
    return candidate.path == prefix or candidate.path.startswith(f"{prefix}/")


def is_same_origin(url: str, seed_url: str) -> bool:
    candidate = urlsplit(url)
    seed = urlsplit(seed_url)
    return (
        candidate.scheme == seed.scheme
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


def _is_document_link(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return any(path.endswith(suffix) for suffix in _DOCUMENT_SUFFIXES)


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
        if _is_document_link(absolute):
            file_links.append(absolute)
        else:
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
