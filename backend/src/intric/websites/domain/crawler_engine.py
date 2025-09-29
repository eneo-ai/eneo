from enum import Enum


class CrawlerEngine(str, Enum):
    """Represents available crawler engines for website crawling."""

    SCRAPY = "scrapy"
    CRAWL4AI = "crawl4ai"