from scrapy import signals
from scrapy.http import Request

from intric.main.logging import get_logger

logger = get_logger(__name__)


class ForceHttp11Middleware:
    """Middleware to force HTTP/1.1 and fix networking issues"""

    def __init__(self):
        logger.info("ForceHttp11Middleware initialized - forcing HTTP/1.1 connections")

    @classmethod
    def from_crawler(cls, crawler):
        o = cls()
        crawler.signals.connect(o.spider_opened, signal=signals.spider_opened)
        return o

    def spider_opened(self, spider):
        logger.info(f"ForceHttp11Middleware: Spider {spider.name} opened - HTTP/1.1 mode active")

    def process_request(self, request: Request, spider):
        # Force HTTP/1.1 by setting connection headers
        request.headers['Connection'] = 'close'  # Prevent keep-alive issues
        request.headers['HTTP-Version'] = '1.1'

        # Remove HTTP/2 specific headers that might cause issues
        headers_to_remove = [
            'Sec-Ch-Ua', 'Sec-Ch-Ua-Mobile', 'Sec-Ch-Ua-Platform',
            'Sec-Fetch-Dest', 'Sec-Fetch-Mode', 'Sec-Fetch-Site', 'Sec-Fetch-User'
        ]

        for header in headers_to_remove:
            if header in request.headers:
                del request.headers[header]

        logger.debug(f"Forced HTTP/1.1 for request: {request.url}")
        return None  # Continue processing