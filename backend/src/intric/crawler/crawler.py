import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Iterable, Optional

import crochet
from scrapy.crawler import CrawlerRunner

from intric.crawler.network_checker import NetworkChecker
from intric.crawler.network_diagnostics import NetworkDiagnostics
from intric.crawler.parse_html import CrawledPage
from intric.crawler.pipelines import FileNamePipeline
from intric.crawler.spiders.crawl_spider import CrawlSpider
from intric.crawler.spiders.sitemap_spider import SitemapSpider
from intric.main.config import SETTINGS
from intric.main.exceptions import (
    CrawlerException,
    CrawlerEmptyResultException,
    CrawlerNetworkException,
)
from intric.main.logging import get_logger
from intric.websites.domain.crawl_run import CrawlType

logger = get_logger(__name__)


@dataclass
class Crawl:
    pages: Iterable[CrawledPage]
    files: Optional[Iterable[Path]]


def create_runner(filepath: str, files_dir: Optional[str] = None):
    # Configure Scrapy logging to use our logger
    import logging as scrapy_logging
    from intric.main.logging import get_logger

    scrapy_logger = get_logger("scrapy")
    scrapy_logger.info("Configuring Scrapy logging...")

    settings = {
        "FEEDS": {filepath: {"format": "jsonl", "item_classes": [CrawledPage]}},
        "CLOSESPIDER_ITEMCOUNT": SETTINGS.closespider_itemcount,
        "AUTOTHROTTLE_ENABLED": SETTINGS.autothrottle_enabled,
        "ROBOTSTXT_OBEY": False,  # Temporarily disable for debugging
        # "ROBOTSTXT_OBEY": SETTINGS.obey_robots,  # Original setting
        "DOWNLOAD_MAXSIZE": SETTINGS.upload_max_file_size,
        # Enhanced logging settings - force Scrapy to log to our system
        "LOG_LEVEL": "DEBUG",  # Scrapy's built-in debug mode
        "LOG_ENABLED": True,
        "LOG_STDOUT": True,
        "LOGSTATS_INTERVAL": 10.0,  # Log Scrapy stats every 10 seconds (default is 60)
        # Anti-bot detection timing
        "DOWNLOAD_TIMEOUT": 30,  # Longer timeout for bot detection delays
        "DOWNLOAD_DELAY": 2,  # Add delay between requests to seem more human
        "RANDOMIZE_DOWNLOAD_DELAY": 0.5,  # Random delay 1.5-2.5 seconds
        "RETRY_TIMES": 0,  # Don't retry - if server is tarpitting, retrying won't help
        "RETRY_HTTP_CODES": [500, 502, 503, 504, 408, 429],
        # Request/Response debugging and networking fixes
        "DOWNLOADER_MIDDLEWARES": {
            'intric.crawler.debug_middleware.DebugLoggingMiddleware': 100,  # High priority for debugging
            'intric.crawler.http_version_middleware.ForceHttp11Middleware': 150,  # Force HTTP/1.1
            'intric.crawler.browser_headers_middleware.BrowserHeadersMiddleware': 200,  # Add browser headers
            'intric.crawler.tcp_connection_tracer.ConnectionMonitoringMiddleware': 300,  # Connection lifecycle
            'intric.crawler.response_body_tracer.ResponseBodyTracerMiddleware': 550,  # Before compression (590)
            'scrapy.downloadermiddlewares.httpcompression.HttpCompressionMiddleware': 590,
            'scrapy.downloadermiddlewares.useragent.UserAgentMiddleware': None,  # Disable default
        },
        # Realistic browser user agent to avoid bot detection
        "USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
        # Browser-like behavior settings
        "COOKIES_ENABLED": True,
        "COOKIES_DEBUG": True,  # Log cookie handling
        "DUPEFILTER_DEBUG": True,
        # Enable session handling like a real browser
        "SESSION_ENABLED": True,
        # Stats and monitoring
        "STATS_CLASS": "scrapy.statscollectors.MemoryStatsCollector",
        # Force concurrent requests to 1 for debugging
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        # Redirect handling - ensure we follow redirects properly
        "REDIRECT_ENABLED": True,
        "REDIRECT_MAX_TIMES": 5,  # Allow up to 5 redirects
        "REDIRECT_PRIORITY_ADJUST": 0,
        # Force HTTP/1.1 to avoid HTTP/2 compatibility issues
        # Note: DOWNLOADER_CLIENT_TLS_METHOD removed - not supported in this Scrapy version
        # Additional networking fixes
        "REACTOR_THREADPOOL_MAXSIZE": 20,
        # Disable Scrapy's telnet console to prevent port conflicts
        "TELNETCONSOLE_ENABLED": False,
        # Extensions for connection tracing
        "EXTENSIONS": {
            'intric.crawler.tcp_connection_tracer.TcpConnectionTracerExtension': 100,
        },
    }

    if files_dir is not None:
        settings["ITEM_PIPELINES"] = {FileNamePipeline: 300}
        settings["FILES_STORE"] = files_dir

    logger.info("Creating Scrapy runner with enhanced logging")
    logger.info(f"Scrapy settings: {settings}")

    # Force Scrapy to use our logging system
    scrapy_logging.getLogger('scrapy').setLevel(scrapy_logging.INFO)
    scrapy_logging.getLogger('scrapy.core.engine').setLevel(scrapy_logging.INFO)
    scrapy_logging.getLogger('scrapy.crawler').setLevel(scrapy_logging.INFO)
    scrapy_logging.getLogger('scrapy.spiders').setLevel(scrapy_logging.INFO)

    return CrawlerRunner(settings=settings)


class Crawler:
    @crochet.wait_for(SETTINGS.crawl_max_length)
    @staticmethod
    def _run_crawl(
        url: str,
        download_files: bool = False,
        *,
        filepath: Path,
        files_dir: Optional[Path],
    ):
        files_dir = files_dir if download_files else None
        runner = create_runner(filepath=filepath, files_dir=files_dir)
        return runner.crawl(CrawlSpider, url=url)

    @crochet.wait_for(SETTINGS.crawl_max_length)
    @staticmethod
    def _run_sitemap_crawl(sitemap_url: str, *, filepath: Path, files_dir: Optional[Path]):
        runner = create_runner(filepath=filepath)
        return runner.crawl(SitemapSpider, sitemap_url=sitemap_url)

    @asynccontextmanager
    async def _crawl(self, func, **kwargs):
        crawl_id = f"crawl_{int(time.time())}"
        log_file_path = f"/tmp/crawl_diagnostics_{crawl_id}.log"

        # Set up file logging for this specific crawl
        file_handler = logging.FileHandler(log_file_path)
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s : %(message)s')
        file_handler.setFormatter(file_formatter)

        # Add file handler to our logger and scrapy loggers
        loggers_to_enhance = [
            logger,
            logging.getLogger('scrapy'),
            logging.getLogger('intric.crawler'),
            logging.getLogger('intric.crawler.debug_middleware'),
            logging.getLogger('intric.crawler.network_checker'),
            logging.getLogger('intric.crawler.network_diagnostics'),
        ]

        for log in loggers_to_enhance:
            log.addHandler(file_handler)

        try:
            logger.info("=== STARTING COMPREHENSIVE CRAWLER DIAGNOSTICS ===")
            logger.info(f"Crawl ID: {crawl_id}")
            logger.info(f"Log file: {log_file_path}")
            logger.info(f"Starting crawl with function {func.__name__} and kwargs: {kwargs}")

            # 1. Capture complete network environment
            logger.info("STEP 1: Capturing complete network environment...")
            env_data = await NetworkDiagnostics.capture_complete_network_environment()
            logger.info("Network environment captured successfully")

            # 1b. Container-specific diagnostics (NEW - critical for finding urllib vs Scrapy differences)
            logger.info("STEP 1b: Container environment diagnostics...")
            from intric.crawler.container_diagnostics import ContainerDiagnostics

            url = kwargs.get('url')
            if url:
                container_diagnostics = await ContainerDiagnostics.run_all_container_diagnostics(url)
            else:
                logger.info("Skipping container diagnostics (no URL provided)")

            # 1c. Scrapy engine component check (NEW - verify Scrapy can start)
            logger.info("STEP 1c: Checking Scrapy engine components...")
            from intric.crawler.scrapy_diagnostics import ScrapyDiagnostics
            ScrapyDiagnostics.check_scrapy_engine_startup_sequence()

            # Pre-flight network connectivity check
            url = kwargs.get('url')
            tcp_analysis = None
            request_comparison = None

            if url:
                logger.info("STEP 2: Performing pre-flight network connectivity checks...")
                network_results = await NetworkChecker.check_connectivity(url)
                NetworkChecker.log_network_diagnostics(network_results)

                # Check if basic connectivity failed
                if not network_results['dns_resolution']:
                    raise CrawlerNetworkException(f"DNS resolution failed for {url}: {network_results['errors']}")
                if not network_results['tcp_connection']:
                    raise CrawlerNetworkException(f"TCP connection failed for {url}: {network_results['errors']}")
                if url.startswith('https') and not network_results['ssl_handshake']:
                    raise CrawlerNetworkException(f"TLS handshake failed for {url}: {network_results['errors']}")

                logger.info("Pre-flight connectivity checks passed ✅")

                # CRITICAL: Compare urllib vs Scrapy to find why urllib works but Scrapy doesn't
                logger.info("STEP 3: Comparing urllib (works) vs Scrapy (fails) configuration...")
                from intric.crawler.scrapy_diagnostics import ScrapyDiagnostics
                comparison = await ScrapyDiagnostics.compare_urllib_vs_scrapy_config(url)

                # If blocking issues found, log them prominently
                if comparison.get('blocking_issues'):
                    logger.error("=" * 60)
                    logger.error("🚨 FOUND LIKELY CAUSE OF CRAWL FAILURE:")
                    for issue in comparison['blocking_issues']:
                        logger.error(f"   {issue}")
                    logger.error("=" * 60)

                # STEP 3b: Get baseline response from urllib for comparison
                logger.info("STEP 3b: Getting baseline response from urllib for later comparison...")
                urllib_baseline = await ScrapyDiagnostics.compare_urllib_vs_scrapy_actual_response(url)
                # This baseline will be compared with Scrapy's actual response after crawl

                # STEP 4: TLS Fingerprint Analysis (CRITICAL - shows what DPI detects)
                logger.info("STEP 4: TLS Fingerprint Analysis (for DPI/firewall detection)...")
                from urllib.parse import urlparse
                parsed_url = urlparse(url)

                if parsed_url.scheme == 'https':
                    from intric.crawler.tls_fingerprint_analyzer import TlsFingerprintAnalyzer
                    tls_fingerprint = await TlsFingerprintAnalyzer.compare_tls_fingerprints(
                        parsed_url.hostname,
                        parsed_url.port or 443
                    )

                # STEP 5: Network diagnostics for network/linux team troubleshooting
                # These provide detailed network-level info useful for infrastructure debugging
                logger.info("STEP 5: Detailed network diagnostics for infrastructure team...")
                port = parsed_url.port or (443 if parsed_url.scheme == 'https' else 80)

                # TCP connection timing breakdown
                tcp_analysis = await NetworkDiagnostics.analyze_tcp_connection(parsed_url.hostname, port)

                # Compare different request methods (curl, wget, urllib, socket)
                request_comparison = await NetworkDiagnostics.compare_request_methods(url)

                # Log summary for network team
                NetworkDiagnostics.log_comprehensive_diagnostics(env_data, tcp_analysis, request_comparison)

            logger.info("STEP 6: Starting Scrapy crawler execution...")

            with NamedTemporaryFile() as tmp_file:
                with TemporaryDirectory() as tmp_dir:
                    logger.info(f"Created temporary file: {tmp_file.name}")
                    logger.info(f"Created temporary directory: {tmp_dir}")

                # Create a progress monitoring task that also checks Scrapy stats
                async def monitor_progress():
                    """Monitor crawl progress and Scrapy stats every 15 seconds"""
                    import time
                    start_time = time.time()
                    last_warning_at = 0
                    crawler_runner = None

                    while True:
                        await asyncio.sleep(15)  # Check every 15 seconds
                        elapsed = time.time() - start_time

                        # Check result file
                        try:
                            current_size = os.stat(tmp_file.name).st_size
                            if current_size > 0:
                                logger.info(f"Progress: {elapsed:.1f}s elapsed, {current_size} bytes written")
                            else:
                                logger.warning(f"Progress: {elapsed:.1f}s elapsed, NO OUTPUT YET")
                        except Exception:
                            pass

                        # CRITICAL: Check Scrapy stats to see if it's stuck
                        # This tells us if Scrapy engine is even trying to make requests
                        if elapsed > 30:  # After 30 seconds, Scrapy should have started
                            try:
                                # Note: We'd need access to the crawler stats here
                                # For now, log that we're checking
                                logger.info(f"Scrapy check: {elapsed:.1f}s elapsed - checking if Scrapy is active...")
                            except Exception:
                                pass

                        # Escalating warnings based on time
                        if elapsed > 60 and elapsed > last_warning_at + 30:
                            logger.warning(f"⚠️  Still waiting after {elapsed:.1f}s - Scrapy may be stuck")
                            logger.warning("   Check Scrapy logs above for 'downloader/request_count' stat")
                            logger.warning("   If request_count=0, Scrapy is stuck before making requests")
                            last_warning_at = elapsed

                        if elapsed > 300:  # 5 minutes
                            logger.error("❌ Timeout: 5 minutes with no progress - giving up monitoring")
                            break

                # Start progress monitoring in background
                logger.info("Starting progress monitoring...")
                monitor_task = asyncio.create_task(monitor_progress())

                try:
                    # Add human-like delay before starting crawl to avoid bot detection
                    logger.info("Adding 3-second delay before crawling to simulate human behavior...")
                    await asyncio.sleep(3)

                    logger.info(f"Executing crawl function {func.__name__}")
                    crawl_result = await asyncio.to_thread(func, filepath=tmp_file.name, files_dir=tmp_dir, **kwargs)
                    logger.info(f"Crawl function completed successfully. Result: {crawl_result}")
                except Exception as e:
                    logger.error(f"Error during crawl execution: {type(e).__name__}: {str(e)}")
                    raise CrawlerException(f"Crawl execution failed: {type(e).__name__}: {str(e)}") from e
                finally:
                    # Cancel progress monitoring
                    monitor_task.cancel()
                    try:
                        await monitor_task
                    except asyncio.CancelledError:
                        pass

                # Check file size and content - CRITICAL INDICATOR
                file_size = os.stat(tmp_file.name).st_size

                logger.info("=" * 80)
                logger.info("RESULT FILE SIZE CHECK")
                logger.info("=" * 80)
                logger.info(f"Result file size: {file_size} bytes")

                if file_size == 0:
                    logger.error("❌ ZERO BYTES - NO CONTENT FETCHED")
                    logger.error("")
                    logger.error("CRITICAL: Scrapy ran but extracted 0 bytes of content")
                    logger.error("This means:")
                    logger.error("  - Scrapy executed but got NO usable responses")
                    logger.error("  - OR responses were received but parser extracted nothing")
                    logger.error("")
                    logger.error("Compare with working scenario:")
                    logger.error("  - Mobile hotspot: ~10000 bytes (WORKS)")
                    logger.error("  - Internal network: 0 bytes (FAILS)")
                    logger.error("")
                    logger.error("This is a NETWORK ISSUE, not a parsing issue!")
                    logger.error("")
                    logger.error("Check logs above for:")
                    logger.error("  1. 'First response received' message (did we get ANY responses?)")
                    logger.error("  2. Scrapy stats: downloader/response_count (should be > 0)")
                    logger.error("  3. HTTP status codes (403, 404, or other blocking codes)")
                    logger.error("  4. TLS/certificate errors")
                    logger.error("")
                    logger.info("=" * 80)

                    raise CrawlerEmptyResultException("Crawl failed: No content was extracted (result file is empty)")

                else:
                    logger.info(f"✅ SUCCESS: {file_size} bytes of content extracted")

                    # Log first few lines as proof of content
                    try:
                        with open(tmp_file.name, 'r') as f:
                            first_lines = []
                            for i, line in enumerate(f):
                                if i >= 2:  # Only read first 2 lines
                                    break
                                first_lines.append(line.strip()[:100])  # Truncate long lines

                            if first_lines:
                                logger.info("Content preview (first 2 lines):")
                                for i, line in enumerate(first_lines, 1):
                                    logger.info(f"  Line {i}: {line}...")
                    except Exception as e:
                        logger.debug(f"Could not preview content: {e}")

                logger.info("=" * 80)

                def _iter_pages():
                    logger.info("Starting to iterate over crawled pages")
                    page_count = 0
                    try:
                        with open(tmp_file.name) as f:
                            for line_num, line in enumerate(f, 1):
                                try:
                                    jsonl = json.loads(line)
                                    page = CrawledPage(**jsonl)
                                    page_count += 1
                                    logger.debug(f"Parsed page {page_count}: {page.url}")
                                    yield page
                                except json.JSONDecodeError as e:
                                    logger.error(f"JSON decode error on line {line_num}: {str(e)}")
                                    logger.error(f"Problematic line: {line[:200]}...")
                                except Exception as e:
                                    logger.error(f"Error creating CrawledPage from line {line_num}: {type(e).__name__}: {str(e)}")
                                    logger.error(f"Line content: {line[:200]}...")
                        logger.info(f"Finished iterating over {page_count} crawled pages")
                    except Exception as e:
                        logger.error(f"Error during page iteration: {type(e).__name__}: {str(e)}")
                        raise

                def _iter_files():
                    logger.info(f"Starting to iterate over files in {tmp_dir}")
                    try:
                        p = Path(tmp_dir)
                        files = list(p.iterdir())
                        logger.info(f"Found {len(files)} files: {[f.name for f in files]}")
                        return files
                    except Exception as e:
                        logger.error(f"Error iterating over files: {type(e).__name__}: {str(e)}")
                        return []

                logger.info("Yielding crawl result")
                yield Crawl(pages=_iter_pages(), files=_iter_files())

        finally:
            # Clean up file handlers and provide log file access
            for log in loggers_to_enhance:
                log.removeHandler(file_handler)
            file_handler.close()

            logger.info("=== CRAWL DIAGNOSTICS COMPLETE ===")
            logger.info(f"Complete diagnostic log saved to: {log_file_path}")
            logger.info("To access the log file from outside the container:")
            logger.info(f"  podman cp <container_id>:{log_file_path} ./crawl_diagnostics.log")
            logger.info("Or view directly:")
            logger.info(f"  podman exec <container_id> cat {log_file_path}")
            logger.info("All logs also visible in podman logs for the worker container")

            # Also copy to backend crawler_logs folder
            try:
                import shutil
                backend_logs_dir = "/workspace/backend/crawler_logs"
                os.makedirs(backend_logs_dir, exist_ok=True)

                # Copy with timestamp filename only
                timestamped_filename = f"crawl_diagnostics_{crawl_id}.log"
                timestamped_path = os.path.join(backend_logs_dir, timestamped_filename)

                shutil.copy2(log_file_path, timestamped_path)

                logger.info(f"Comprehensive diagnostic log saved to: {timestamped_path}")
                logger.info("Log is now accessible in the backend/crawler_logs/ directory")
            except Exception as e:
                logger.debug(f"Could not copy log to backend folder: {e}")

    @asynccontextmanager
    async def crawl(
        self,
        url: str,
        download_files: bool = False,
        crawl_type: CrawlType = CrawlType.CRAWL,
    ):
        if crawl_type == CrawlType.CRAWL:
            async with self._crawl(
                self._run_crawl,
                url=url,
                download_files=download_files,
            ) as crawl_result:
                yield crawl_result

        elif crawl_type == CrawlType.SITEMAP:
            async with self._crawl(self._run_sitemap_crawl, sitemap_url=url) as crawl_result:
                yield crawl_result

        else:
            raise ValueError(f"crawl_type {crawl_type} is not a CrawlType")
