from urllib.parse import urlparse

import scrapy
from scrapy.http import Response
from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import Rule
from typing_extensions import override

from eneo.crawler.parse_html import parse_file, parse_response


class CrawlSpider(scrapy.spiders.CrawlSpider):  # type: ignore[attr-defined]
    name = "crawlspider"

    def __init__(
        self,
        url: str,
        http_user: str | None = None,
        http_pass: str | None = None,
        *args: object,
        **kwargs: object,
    ) -> None:
        parsed_uri = urlparse(url)

        self.allowed_domains = [parsed_uri.netloc]
        self.start_urls = [url]

        self.rules = [
            Rule(
                LinkExtractor(allow=url),
                callback=parse_response,
                follow=True,
            ),
            Rule(LinkExtractor(deny_extensions=[]), callback=parse_file),
        ]

        # Set up basic authentication if provided
        if http_user and http_pass:
            self.http_user = http_user
            self.http_pass = http_pass
            self.http_auth_domain = parsed_uri.netloc

        super().__init__(*args, **kwargs)  # pyright: ignore[reportUnknownMemberType]  # Scrapy spider __init__ is untyped

    @override
    def parse_start_url(self, response: Response):
        return parse_response(response)
