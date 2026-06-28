import logging
import mimetypes
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from html2text import html2text
from scrapy.http import Response, TextResponse

from eneo.files.text import TextMimeTypes

logger = logging.getLogger(__name__)


# MIME types of linked documents worth downloading and ingesting during a crawl.
# Deliberately kept separate from the upload/attachment allowlist (TextMimeTypes):
# broadening what users may attach must never silently widen crawl scope. HTML is
# excluded on purpose — pages are extracted via parse_response, not ingested as
# standalone files — and legacy .doc/.ppt are excluded since the extractor rejects
# them anyway. Values are sourced from TextMimeTypes so a removed format breaks at
# import time rather than drifting silently.
CRAWLABLE_DOCUMENT_MIMETYPES: frozenset[str] = frozenset(
    {
        TextMimeTypes.MD.value,
        TextMimeTypes.TXT.value,
        TextMimeTypes.PDF.value,
        TextMimeTypes.DOCX.value,
        TextMimeTypes.TEXT_CSV.value,
        TextMimeTypes.APP_CSV.value,
        TextMimeTypes.PPTX.value,
        TextMimeTypes.XLSX.value,
        TextMimeTypes.XLS.value,
        TextMimeTypes.JSON.value,
        TextMimeTypes.XML.value,
        TextMimeTypes.XML_APP.value,
    }
)


@dataclass
class CrawledPage:
    url: str
    title: str
    content: str


def parse_response(response: Response) -> CrawledPage | None:
    # Guard: Skip non-text responses (images, PDFs, binary data)
    # Scrapy callbacks that return None are silently ignored
    if not isinstance(response, TextResponse):
        return None

    ct_raw = response.headers.get(b"Content-Type")
    content_type: str = (ct_raw or b"").decode("utf-8").lower()
    if "application/json" in content_type:
        # For JSON responses, use the body as-is with URL as title
        return CrawledPage(url=response.url, title=response.url, content=response.text)

    # Handle HTML responses
    soup = BeautifulSoup(response.body, "lxml")

    # Replace relative links with absolute
    for url in soup.find_all("a", href=True):
        url["href"] = urljoin(response.url, url["href"])

    content = html2text(str(soup))
    # response.css() is from untyped Scrapy; its return type is partially unknown.
    title: str = response.css("title::text").get() or response.url  # pyright: ignore[reportUnknownMemberType]  # Scrapy has no py.typed stubs
    url = response.url

    return CrawledPage(url=url, title=title, content=content)


def parse_file(response: Response) -> dict[str, list[str]] | None:
    ct_raw = response.headers.get(b"Content-Type")
    content_type: str = ""
    if ct_raw:
        content_type = ct_raw.decode("utf-8", errors="ignore").lower()
    else:
        guessed_type, _ = mimetypes.guess_type(response.url)
        if guessed_type:
            content_type = guessed_type.lower()
        else:
            logger.debug(
                "Skipping file without content-type header",
                extra={"url": response.url},
            )
            return None

    base_type = content_type.split(";")[0].strip()
    if base_type in CRAWLABLE_DOCUMENT_MIMETYPES:
        return {"file_urls": [response.url]}

    return None
