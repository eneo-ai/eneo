from dataclasses import dataclass
import logging
import mimetypes
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from html2text import html2text
from scrapy.http import Response, TextResponse

from intric.files.text import TextMimeTypes

logger = logging.getLogger(__name__)


@dataclass
class CrawledPage:
    url: str
    title: str
    content: str


def parse_response(response: Response):
    # Guard: Skip non-text responses (images, PDFs, binary data)
    # Scrapy callbacks that return None are silently ignored
    if not isinstance(response, TextResponse):
        return None

    # Handle JSON responses (e.g., API endpoints)
    content_type = response.headers.get(b"Content-Type", b"").decode("utf-8").lower()
    if "application/json" in content_type:
        # For JSON responses, use the body as-is with URL as title
        return CrawledPage(url=response.url, title=response.url, content=response.text)

    # Handle HTML responses
    soup = BeautifulSoup(response.body, "lxml")

    # Replace relative links with absolute
    for url in soup.find_all("a", href=True):
        url["href"] = urljoin(response.url, url["href"])

    content = html2text(str(soup))
    title = response.css("title::text").get()
    url = response.url

    return CrawledPage(url=url, title=title, content=content)


def parse_file(response: Response):
    content_type_header = response.headers.get(b"Content-Type")
    content_type = ""
    if content_type_header:
        content_type = content_type_header.decode("utf-8", errors="ignore").lower()
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

    if TextMimeTypes.has_value(content_type):
        return {"file_urls": [response.url]}

    return None
