from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from html2text import html2text
from scrapy.http import Response

from intric.files.text import TextMimeTypes
from intric.main.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CrawledPage:
    url: str
    title: str
    content: str


def parse_response(response: Response):
    logger.info(f"Parsing response from URL: {response.url}")
    logger.debug(f"Response status: {response.status}")
    logger.debug(f"Response headers: {dict(response.headers)}")
    logger.debug(f"Response body length: {len(response.body)} bytes")

    try:
        # Parse HTML with BeautifulSoup
        logger.debug("Creating BeautifulSoup object")
        soup = BeautifulSoup(response.body, "lxml")

        if not soup:
            logger.warning(f"BeautifulSoup returned empty soup for URL: {response.url}")
            return None

        # Replace relative links with absolute
        logger.debug("Processing relative links")
        link_count = 0
        try:
            for url_tag in soup.find_all("a", href=True):
                original_href = url_tag["href"]
                absolute_href = urljoin(response.url, original_href)
                url_tag["href"] = absolute_href
                link_count += 1
                if link_count <= 5:  # Log first 5 links for debugging
                    logger.debug(f"Converted link: {original_href} -> {absolute_href}")
            logger.debug(f"Processed {link_count} links")
        except Exception as e:
            logger.error(f"Error processing links: {type(e).__name__}: {str(e)}")

        # Convert to text
        logger.debug("Converting HTML to text")
        try:
            content = html2text(str(soup))
            logger.debug(f"Converted content length: {len(content)} characters")
        except Exception as e:
            logger.error(f"Error converting HTML to text: {type(e).__name__}: {str(e)}")
            content = str(soup.get_text())  # Fallback to simple text extraction
            logger.info(f"Used fallback text extraction, length: {len(content)} characters")

        # Extract title
        logger.debug("Extracting page title")
        try:
            title = response.css("title::text").get()
            if title:
                title = title.strip()
                logger.debug(f"Extracted title: {title[:100]}...")
            else:
                logger.warning(f"No title found for URL: {response.url}")
                title = ""
        except Exception as e:
            logger.error(f"Error extracting title: {type(e).__name__}: {str(e)}")
            title = ""

        url = response.url

        # Validate extracted data
        if not content or len(content.strip()) == 0:
            logger.warning(f"No content extracted from URL: {response.url}")
            return None

        crawled_page = CrawledPage(url=url, title=title, content=content)
        logger.info(f"Successfully parsed page: {url} (title: '{title[:50]}...', content: {len(content)} chars)")
        return crawled_page

    except Exception as e:
        logger.error(f"Unexpected error parsing response from {response.url}: {type(e).__name__}: {str(e)}")
        logger.error(f"Response details - Status: {response.status}, Body length: {len(response.body)}")
        return None


def parse_file(response: Response):
    logger.info(f"Parsing file from URL: {response.url}")
    logger.debug(f"Response status: {response.status}")
    logger.debug(f"Response headers: {dict(response.headers)}")

    try:
        # Check if Content-Type header exists
        if b"Content-Type" not in response.headers:
            logger.warning(f"No Content-Type header found for file URL: {response.url}")
            return None

        content_type = response.headers[b"Content-Type"].decode("utf-8")
        logger.debug(f"Content-Type: {content_type}")

        # Check if it's a text file type
        if TextMimeTypes.has_value(content_type):
            logger.info(f"File {response.url} is a text file type ({content_type}), adding to file_urls")
            return {"file_urls": [response.url]}
        else:
            logger.debug(f"File {response.url} is not a text file type ({content_type}), skipping")
            return None

    except UnicodeDecodeError as e:
        logger.error(f"Unicode decode error for Content-Type header from {response.url}: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error parsing file from {response.url}: {type(e).__name__}: {str(e)}")
        logger.error(f"Response details - Status: {response.status}, Headers: {dict(response.headers)}")
        return None
