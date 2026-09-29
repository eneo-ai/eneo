"""CrawlSpider scopes the crawl to the start URL's host."""

from eneo.crawler.spiders.crawl_spider import CrawlSpider


def test_allowed_domains_is_host_without_port():
    spider = CrawlSpider(url="https://example.com:8443/docs/")
    assert spider.allowed_domains == ["example.com"]
    assert spider.start_urls == ["https://example.com:8443/docs/"]


def test_http_auth_domain_keeps_the_port():
    spider = CrawlSpider(url="https://example.com:8443/", http_user="u", http_pass="p")
    assert spider.http_auth_domain == "example.com:8443"
