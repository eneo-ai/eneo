"""
Scrapy-specific diagnostics to identify why Scrapy behaves differently from urllib/curl
"""
import ssl
from typing import Dict, Any
from urllib.parse import urlparse

from intric.main.logging import get_logger

logger = get_logger(__name__)


class ScrapyDiagnostics:
    """Compare Scrapy/Twisted behavior with standard library"""

    @staticmethod
    async def compare_urllib_vs_scrapy_config(url: str) -> Dict[str, Any]:
        """
        Critical comparison: Why does urllib work but Scrapy doesn't?
        Focus on the 3 most likely causes based on user's evidence
        """
        logger.info("=== URLLIB vs SCRAPY: Why urllib works but Scrapy doesn't? ===")

        parsed_url = urlparse(url)
        comparison = {'url': url, 'blocking_issues': [], 'config_differences': []}

        # Test 1: robots.txt blocking (check but we have ROBOTSTXT_OBEY=False)
        logger.info("1. Checking robots.txt (NOTE: ROBOTSTXT_OBEY=False, so this shouldn't block)...")
        try:
            robots_url = f"{parsed_url.scheme}://{parsed_url.netloc}/robots.txt"
            import urllib.request
            with urllib.request.urlopen(robots_url, timeout=10) as response:
                robots_content = response.read().decode('utf-8', errors='ignore')

                # Check for blanket disallow (only full path, not partial)
                # Need to check for "Disallow: /" followed by newline or space, not "Disallow: /some/path"
                import re
                blanket_disallow = re.search(r'Disallow:\s*/\s*$', robots_content, re.MULTILINE)

                if blanket_disallow and 'User-agent: *' in robots_content:
                    logger.error("🚫 robots.txt has 'Disallow: /' (blocks all)")
                    logger.error("   BUT ROBOTSTXT_OBEY=False, so Scrapy ignores this")
                    logger.error(f"robots.txt excerpt: {robots_content[:300]}")
                else:
                    logger.info("✅ robots.txt doesn't have blanket Disallow: /")
                    logger.info("   (Has specific path blocks only)")
        except Exception as e:
            logger.info(f"robots.txt not found or accessible: {e}")

        # Test 2: TLS certificate validation differences
        logger.info("2. Checking TLS/SSL implementation differences...")
        if parsed_url.scheme == 'https':
            try:
                from OpenSSL import SSL
                openssl_version = SSL.SSLeay_version(SSL.SSLEAY_VERSION).decode()
                python_ssl_version = ssl.OPENSSL_VERSION

                if openssl_version != python_ssl_version:
                    logger.warning("⚠️  TLS library mismatch:")
                    logger.warning(f"   Python ssl uses: {python_ssl_version}")
                    logger.warning(f"   Twisted uses: {openssl_version}")
                    comparison['config_differences'].append(f"TLS: Python({python_ssl_version}) vs Twisted({openssl_version})")
            except Exception as e:
                logger.debug(f"Could not compare TLS versions: {e}")

        # Test 3: User-Agent / Headers filtering
        logger.info("3. Checking if server filters based on User-Agent...")
        try:
            from intric.crawler.crawler import create_runner
            import tempfile

            with tempfile.NamedTemporaryFile() as tmp:
                runner = create_runner(filepath=tmp.name)
                scrapy_ua = runner.settings.get('USER_AGENT')

                # Compare user agents
                logger.info("   urllib User-Agent: Python-urllib/3.x")
                logger.info(f"   Scrapy User-Agent: {scrapy_ua}")

                if 'bot' in scrapy_ua.lower() or 'spider' in scrapy_ua.lower():
                    logger.warning("⚠️  Scrapy User-Agent contains 'bot' or 'spider' - may be filtered")
                    comparison['blocking_issues'].append("User-Agent may trigger bot detection")

        except Exception as e:
            logger.error(f"Could not check User-Agent: {e}")

        # Summary
        if comparison['blocking_issues']:
            logger.error(f"❌ Found {len(comparison['blocking_issues'])} blocking issues:")
            for issue in comparison['blocking_issues']:
                logger.error(f"   - {issue}")
        else:
            logger.info("✅ No obvious blocking issues found")

        if comparison['config_differences']:
            logger.warning(f"⚠️  Found {len(comparison['config_differences'])} configuration differences:")
            for diff in comparison['config_differences']:
                logger.warning(f"   - {diff}")

        return comparison

    @staticmethod
    def log_scrapy_stats_realtime(crawler_stats):
        """
        Log critical Scrapy stats that show if crawler is making progress
        Only log if something interesting happened or if stuck
        """
        try:
            stats = crawler_stats.get_stats()

            requests = stats.get('downloader/request_count', 0)
            responses = stats.get('downloader/response_count', 0)
            items = stats.get('item_scraped_count', 0)

            # CRITICAL: If no requests after 30s, Scrapy is stuck before even starting
            if requests == 0:
                logger.error("🚫 SCRAPY STUCK: No requests sent yet!")
                logger.error("   This means Scrapy engine hasn't started making requests")
                logger.error("   Possible causes: robots.txt check hanging, DNS issue, or engine not starting")
                return

            # If requests sent but no responses, network issue
            if requests > 0 and responses == 0:
                logger.error(f"🚫 NETWORK ISSUE: {requests} requests sent, but 0 responses received")
                logger.error("   Requests are leaving Scrapy but no responses coming back")
                return

            # If responses but no items, parsing issue
            if responses > 0 and items == 0:
                logger.warning(f"⚠️  PARSING ISSUE: {responses} responses received, but 0 items scraped")
                logger.warning("   Pages are loading but parser isn't extracting content")
                return

            # Normal progress
            if requests > 0:
                logger.info(f"Scrapy progress: {requests} requests, {responses} responses, {items} items")

            # Log any errors
            for key, value in stats.items():
                if value > 0 and ('error' in key.lower() or 'exception' in key.lower() or '403' in str(key) or '404' in str(key)):
                    logger.error(f"Scrapy error: {key}={value}")

        except Exception as e:
            logger.debug(f"Could not log stats: {e}")

    @staticmethod
    def enable_scrapy_debug_mode(settings_dict):
        """
        Enable Scrapy's built-in debug mode for maximum visibility
        This is cleaner than adding our own logging everywhere
        """
        # Enable Scrapy's most verbose logging
        settings_dict['LOG_LEVEL'] = 'DEBUG'
        settings_dict['LOG_ENABLED'] = True

        # Enable debugging for specific components that matter
        settings_dict['DUPEFILTER_DEBUG'] = True
        settings_dict['COOKIES_DEBUG'] = True

        # Log stats more frequently
        settings_dict['LOGSTATS_INTERVAL'] = 10.0  # Log stats every 10 seconds instead of 60

        logger.info("✅ Scrapy debug mode enabled: LOG_LEVEL=DEBUG, stats every 10s")

    @staticmethod
    def check_scrapy_engine_startup_sequence():
        """
        Log the Scrapy engine startup sequence to detect where it gets stuck
        This helps identify if engine fails to start vs. starts but hangs
        """
        logger.info("=== SCRAPY ENGINE STARTUP SEQUENCE ===")

        try:
            from scrapy import __version__ as scrapy_version

            logger.info(f"Scrapy version: {scrapy_version}")

            # Check Scrapy's Twisted integration
            try:
                from scrapy.utils.reactor import install_reactor
                logger.info("✅ Scrapy reactor installer available")
            except ImportError:
                logger.warning("⚠️  Scrapy reactor installer not available")

            # Check download handlers
            try:
                from scrapy.core.downloader.handlers.http11 import HTTP11DownloadHandler
                logger.info("✅ HTTP11DownloadHandler available")
            except ImportError as e:
                logger.error(f"❌ HTTP11DownloadHandler import failed: {e}")

            # Check TLS support
            try:
                from twisted.internet import ssl as twisted_ssl
                from OpenSSL import SSL

                logger.info(f"✅ Twisted TLS available: OpenSSL {SSL.SSLeay_version(SSL.SSLEAY_VERSION).decode()}")

            except ImportError as e:
                logger.error(f"❌ Twisted TLS not available: {e}")

        except Exception as e:
            logger.error(f"Error checking Scrapy components: {e}")

        logger.info("=" * 60)

    @staticmethod
    async def diagnose_scrapy_hang_point(url: str) -> Dict[str, Any]:
        """
        Try to determine exactly WHERE Scrapy hangs
        Uses a test spider that logs every phase of execution
        """
        logger.info("=== DIAGNOSING SCRAPY HANG POINT ===")
        logger.info("This test determines if Scrapy hangs before/during/after making requests")

        diagnosis = {
            'url': url,
            'phases': {},
            'suspected_hang_point': None
        }

        # We'll check various phases and log timestamps
        phases = [
            'spider_class_loaded',
            'crawler_runner_created',
            'spider_instantiated',
            'start_requests_generated',
            'request_queued',
            'downloader_invoked',
            'response_received',
            'item_scraped'
        ]

        # This will be populated during actual crawl
        # For now, document what we're looking for
        logger.info("During crawl, monitoring these phases:")
        for i, phase in enumerate(phases, 1):
            logger.info(f"   {i}. {phase}")

        logger.info("")
        logger.info("If hang occurs, last completed phase indicates root cause:")
        logger.info("   - Before 'crawler_runner_created': Import/setup issue")
        logger.info("   - Before 'spider_instantiated': Crawler configuration issue")
        logger.info("   - Before 'request_queued': Spider initialization issue")
        logger.info("   - Before 'downloader_invoked': Engine not starting")
        logger.info("   - Before 'response_received': Network/DNS/TLS issue")
        logger.info("   - Before 'item_scraped': Parsing issue")

        logger.info("=" * 60)
        return diagnosis

    @staticmethod
    async def compare_urllib_vs_scrapy_actual_response(url: str) -> Dict[str, Any]:
        """
        Make the SAME request with both urllib and Scrapy to compare responses
        This will show exactly what differs between working (urllib) and failing (Scrapy)
        """
        logger.info("=" * 80)
        logger.info("URLLIB vs SCRAPY: ACTUAL RESPONSE COMPARISON")
        logger.info("=" * 80)
        logger.info(f"Testing URL: {url}")

        comparison = {
            'url': url,
            'urllib_response': {},
            'scrapy_response': {},
            'differences': []
        }

        # 1. Test with urllib (what WORKS)
        logger.info("\n1. Testing with urllib (working method)...")
        try:
            import urllib.request
            import time

            start = time.time()
            req = urllib.request.Request(url)

            with urllib.request.urlopen(req, timeout=30) as response:
                urllib_body = response.read()
                elapsed = time.time() - start

                comparison['urllib_response'] = {
                    'status': response.getcode(),
                    'body_size': len(urllib_body),
                    'headers': dict(response.headers),
                    'time_ms': elapsed * 1000,
                    'success': True
                }

                logger.info("✅ urllib SUCCESS:")
                logger.info(f"   Status: {response.getcode()}")
                logger.info(f"   Body size: {len(urllib_body)} bytes")
                logger.info(f"   Time: {elapsed * 1000:.0f}ms")
                logger.info(f"   Content-Type: {response.headers.get('Content-Type')}")
                logger.info(f"   Content-Length header: {response.headers.get('Content-Length')}")

                # Save first 500 bytes for comparison
                comparison['urllib_response']['body_preview'] = urllib_body[:500]

        except Exception as e:
            logger.error(f"❌ urllib FAILED: {e}")
            comparison['urllib_response'] = {
                'success': False,
                'error': str(e)
            }

        # 2. Compare responses if both succeeded
        if comparison['urllib_response'].get('success'):
            urllib_size = comparison['urllib_response']['body_size']
            urllib_headers = comparison['urllib_response']['headers']

            logger.info("\n2. Key differences to check when Scrapy runs:")
            logger.info(f"   Expected body size: {urllib_size} bytes")
            logger.info(f"   Expected Content-Type: {urllib_headers.get('Content-Type')}")

            if urllib_size == 0:
                logger.warning("⚠️  Even urllib got 0 bytes - server issue, not Scrapy issue")
            else:
                logger.info("\n3. When Scrapy returns 0 bytes but urllib gets {urllib_size} bytes:")
                logger.info("   DEFINITIVE PROOF of Scrapy-specific issue")
                logger.info("")
                logger.info("   Check logs for:")
                logger.info("     - Content-Length header mismatch")
                logger.info("     - Compression/decompression errors")
                logger.info("     - Chunked encoding failures")
                logger.info("     - Middleware stripping content")

        logger.info("=" * 80)
        return comparison