from urllib.parse import urlparse

import scrapy
from scrapy.http import Response

from intric.crawler.parse_html import parse_response


class SitemapSpider(scrapy.spiders.SitemapSpider):
    name = "sitemapspider"

    def __init__(
        self,
        sitemap_url: str,
        http_user: str = None,
        http_pass: str = None,
        *args,
        **kwargs,
    ):
        self.sitemap_urls = [sitemap_url]

        # Set up basic authentication if provided
        if http_user and http_pass:
            parsed_uri = urlparse(sitemap_url)
            self.http_user = http_user
            self.http_pass = http_pass
            self.http_auth_domain = parsed_uri.netloc

        super().__init__(*args, **kwargs)

    def parse(self, response: Response):
        return parse_response(response)
