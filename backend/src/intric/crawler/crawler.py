import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Iterable, Optional

import crochet
from scrapy.crawler import CrawlerRunner

from intric.crawler.parse_html import CrawledPage
from intric.crawler.pipelines import FileNamePipeline
from intric.crawler.spiders.crawl_spider import CrawlSpider
from intric.crawler.spiders.sitemap_spider import SitemapSpider
from intric.main.config import get_settings
from intric.main.exceptions import CrawlerException
from intric.websites.domain.crawl_run import CrawlType


@dataclass
class Crawl:
    pages: Iterable[CrawledPage]
    files: Optional[Iterable[Path]]


def create_runner(filepath: str, files_dir: Optional[str] = None):
    app_settings = get_settings()
    settings = {
        "FEEDS": {filepath: {"format": "jsonl", "item_classes": [CrawledPage]}},
        "CLOSESPIDER_ITEMCOUNT": app_settings.closespider_itemcount,
        "AUTOTHROTTLE_ENABLED": app_settings.autothrottle_enabled,
        "ROBOTSTXT_OBEY": app_settings.obey_robots,
        "DOWNLOAD_MAXSIZE": app_settings.upload_max_file_size,
        # Timeout settings to fail faster on unreachable sites
        # Why: Default 180s timeout × 3 retries = ~13 min waste per unreachable site
        # These are per-REQUEST timeouts, NOT total crawl time (crawl_max_length handles that)
        "DOWNLOAD_TIMEOUT": 90,  # 90s per request (conservative, down from 180s default)
        "DNS_TIMEOUT": 30,  # 30s for DNS resolution (down from 60s default)
        "RETRY_TIMES": 2,  # 2 retries (3 total attempts) - keep Scrapy default
        "RETRY_ENABLED": True,
    }

    if files_dir is not None:
        settings["ITEM_PIPELINES"] = {FileNamePipeline: 300}
        settings["FILES_STORE"] = files_dir

    return CrawlerRunner(settings=settings)


class Crawler:
    @crochet.wait_for(get_settings().crawl_max_length)
    @staticmethod
    def _run_crawl(
        url: str,
        download_files: bool = False,
        *,
        filepath: Path,
        files_dir: Optional[Path],
        http_user: str = None,
        http_pass: str = None,
    ):
        files_dir = files_dir if download_files else None
        runner = create_runner(filepath=filepath, files_dir=files_dir)
        return runner.crawl(CrawlSpider, url=url, http_user=http_user, http_pass=http_pass)

    @crochet.wait_for(get_settings().crawl_max_length)
    @staticmethod
    def _run_sitemap_crawl(
        sitemap_url: str,
        *,
        filepath: Path,
        files_dir: Optional[Path],
        http_user: str = None,
        http_pass: str = None,
    ):
        runner = create_runner(filepath=filepath)
        return runner.crawl(SitemapSpider, sitemap_url=sitemap_url, http_user=http_user, http_pass=http_pass)

    @asynccontextmanager
    async def _crawl(self, func, **kwargs):
        with NamedTemporaryFile() as tmp_file:
            with TemporaryDirectory() as tmp_dir:
                await asyncio.to_thread(func, filepath=tmp_file.name, files_dir=tmp_dir, **kwargs)

                # If the result file is empty
                # (This will fail if the expected result is no pages but some files)
                if os.stat(tmp_file.name).st_size == 0:
                    # Extract URL for better error context in logs
                    url = kwargs.get("url") or kwargs.get("sitemap_url", "unknown")
                    raise CrawlerException(f"Crawl failed for {url}: no pages returned")

                def _iter_pages():
                    with open(tmp_file.name) as f:
                        for line in f:
                            jsonl = json.loads(line)
                            yield CrawledPage(**jsonl)

                def _iter_files():
                    p = Path(tmp_dir)
                    return p.iterdir()

                yield Crawl(pages=_iter_pages(), files=_iter_files())

    @asynccontextmanager
    async def crawl(
        self,
        url: str,
        download_files: bool = False,
        crawl_type: CrawlType = CrawlType.CRAWL,
        http_user: str = None,
        http_pass: str = None,
    ):
        if crawl_type == CrawlType.CRAWL:
            async with self._crawl(
                self._run_crawl,
                url=url,
                download_files=download_files,
                http_user=http_user,
                http_pass=http_pass,
            ) as crawl_result:
                yield crawl_result

        elif crawl_type == CrawlType.SITEMAP:
            async with self._crawl(
                self._run_sitemap_crawl,
                sitemap_url=url,
                http_user=http_user,
                http_pass=http_pass,
            ) as crawl_result:
                yield crawl_result

        else:
            raise ValueError(f"crawl_type {crawl_type} is not a CrawlType")
