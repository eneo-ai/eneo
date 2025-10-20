from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from html2text import html2text
from scrapy.http import Response

from intric.files.text import TextMimeTypes


@dataclass
class CrawledPage:
    url: str
    title: str
    content: str


def parse_response(response: Response):
    # Handle JSON responses (e.g., API endpoints)
    content_type = response.headers.get(b"Content-Type", b"").decode("utf-8").lower()
    if "application/json" in content_type:
        # For JSON responses, use the body as-is with URL as title
        return CrawledPage(
            url=response.url,
            title=response.url,
            content=response.text
        )

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
    if TextMimeTypes.has_value(response.headers[b"Content-Type"].decode("utf-8")):
        return {"file_urls": [response.url]}
