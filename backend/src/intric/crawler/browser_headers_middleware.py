from scrapy import signals
from scrapy.http import Request

from intric.main.logging import get_logger

logger = get_logger(__name__)


class BrowserHeadersMiddleware:
    """Middleware to add realistic browser headers to avoid bot detection"""

    def __init__(self):
        logger.info("BrowserHeadersMiddleware initialized")

        # Realistic browser headers
        self.browser_headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Cache-Control': 'max-age=0',
            'Sec-Ch-Ua': '"Chromium";v="118", "Google Chrome";v="118", "Not=A?Brand";v="99"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
        }

    @classmethod
    def from_crawler(cls, crawler):
        o = cls()
        crawler.signals.connect(o.spider_opened, signal=signals.spider_opened)
        return o

    def spider_opened(self, spider):
        logger.info(f"BrowserHeadersMiddleware: Spider {spider.name} opened")

    def process_request(self, request: Request, spider):
        # Add realistic browser headers to every request
        for header_name, header_value in self.browser_headers.items():
            request.headers[header_name] = header_value

        # Add a realistic Referer for non-start URLs
        if request.url not in spider.start_urls:
            # Use the domain's main page as referer
            from urllib.parse import urlparse
            parsed = urlparse(request.url)
            referer = f"{parsed.scheme}://{parsed.netloc}/"
            request.headers['Referer'] = referer

        logger.debug(f"Added browser headers to request: {request.url}")
        return None  # Continue processing