from urllib.parse import urlparse

import scrapy
from scrapy.http import Response
from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import Rule

from intric.crawler.parse_html import parse_file, parse_response
from intric.main.logging import get_logger

logger = get_logger(__name__)


class CrawlSpider(scrapy.spiders.CrawlSpider):
    name = "crawlspider"

    def __init__(
        self,
        url: str,
        *args,
        **kwargs,
    ):
        logger.info(f"Initializing CrawlSpider for URL: {url}")

        parsed_uri = urlparse(url)
        logger.info(f"Parsed URI - scheme: {parsed_uri.scheme}, netloc: {parsed_uri.netloc}, path: {parsed_uri.path}")

        self.allowed_domains = [parsed_uri.netloc]
        self.start_urls = [url]

        logger.info(f"Allowed domains: {self.allowed_domains}")
        logger.info(f"Start URLs: {self.start_urls}")

        # Create rules with logging wrappers
        # FIXED: The original 'allow=url' rule was too restrictive and didn't handle redirects
        # Many sites redirect URLs (e.g., /path -> /kommun/path), breaking the exact match

        logger.info(f"Original URL: {url}")

        # For single-page crawling, we want to allow:
        # 1. The exact URL
        # 2. Any redirected version of that URL on the same domain
        # 3. Any subpath that might be the redirect target

        flexible_pattern = f"^https?://{parsed_uri.netloc}/.*"

        logger.info(f"Using flexible domain pattern: {flexible_pattern}")
        logger.info("This pattern allows redirects and subpaths on the same domain")

        self.rules = [
            Rule(
                LinkExtractor(allow=flexible_pattern),  # Much more flexible rule
                callback=self._parse_response_with_logging,
                follow=True,
            ),
            Rule(LinkExtractor(deny_extensions=[]), callback=self._parse_file_with_logging),
        ]

        logger.info(f"Created {len(self.rules)} crawling rules")
        logger.info(f"Rule 1: LinkExtractor(allow='{flexible_pattern}') with follow=True - HANDLES REDIRECTS!")
        logger.info("Rule 2: LinkExtractor(deny_extensions=[]) for file downloads")

        super().__init__(*args, **kwargs)
        logger.info("CrawlSpider initialization complete")

    def parse_start_url(self, response: Response):
        logger.info(f"Parsing start URL: {response.url}")
        logger.debug(f"Start URL response status: {response.status}")
        try:
            result = parse_response(response)
            if result:
                logger.info(f"Successfully parsed start URL: {response.url}")
            else:
                logger.warning(f"No result from parsing start URL: {response.url}")
            return result
        except Exception as e:
            logger.error(f"Error parsing start URL {response.url}: {type(e).__name__}: {str(e)}")
            return None

    def _parse_response_with_logging(self, response: Response):
        logger.info(f"Rule-based parsing response from: {response.url}")
        logger.debug(f"Response status: {response.status}")
        try:
            result = parse_response(response)
            if result:
                logger.info(f"Successfully parsed response: {response.url}")
            else:
                logger.warning(f"No result from parsing response: {response.url}")
            return result
        except Exception as e:
            logger.error(f"Error parsing response {response.url}: {type(e).__name__}: {str(e)}")
            return None

    def _parse_file_with_logging(self, response: Response):
        logger.info(f"Rule-based parsing file from: {response.url}")
        logger.debug(f"File response status: {response.status}")
        try:
            result = parse_file(response)
            if result:
                logger.info(f"Successfully parsed file: {response.url}")
            else:
                logger.debug(f"File not processed (not a text file): {response.url}")
            return result
        except Exception as e:
            logger.error(f"Error parsing file {response.url}: {type(e).__name__}: {str(e)}")
            return None

    def start_requests(self):
        logger.info(f"Generating start requests for URLs: {self.start_urls}")
        for url in self.start_urls:
            logger.info(f"Creating request for start URL: {url}")
            logger.info(f"robots.txt obey setting: {self.settings.get('ROBOTSTXT_OBEY')}")
            if self.settings.get('ROBOTSTXT_OBEY'):
                logger.warning("robots.txt obedience is ENABLED - this may block crawling!")
                logger.info(f"Check robots.txt at: {url}/robots.txt")
            yield scrapy.Request(url, self.parse_start_url)

    def spider_opened(self, spider):
        logger.info(f"Spider {spider.name} opened")
        logger.info(f"Spider stats: {spider.crawler.stats.get_stats()}")

    def spider_closed(self, spider, reason):
        logger.info(f"Spider {spider.name} closed with reason: {reason}")
        final_stats = spider.crawler.stats.get_stats()
        logger.info(f"Final spider stats: {final_stats}")

        # Log key metrics
        requests_count = final_stats.get('downloader/request_count', 0)
        response_count = final_stats.get('downloader/response_count', 0)
        items_scraped = final_stats.get('item_scraped_count', 0)

        logger.info(f"Requests made: {requests_count}")
        logger.info(f"Responses received: {response_count}")
        logger.info(f"Items scraped: {items_scraped}")

        if requests_count == 0:
            logger.error("NO REQUESTS WERE MADE - This indicates a fundamental issue")
        elif response_count == 0:
            logger.error("NO RESPONSES RECEIVED - Network/timeout/blocking issue")
        elif items_scraped == 0:
            logger.error("NO ITEMS SCRAPED - Parsing issue or empty responses")
