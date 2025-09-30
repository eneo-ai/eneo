"""
Response body tracer middleware - hooks into Twisted to track content reception
This helps diagnose if content is being lost during transfer (chunked encoding, compression, etc.)
"""
from scrapy import signals

from intric.main.logging import get_logger

logger = get_logger(__name__)


class ResponseBodyTracerMiddleware:
    """
    Trace response body reception to diagnose 0-byte responses
    Hooks into Twisted's HTTP protocol to see actual bytes received
    """

    def __init__(self):
        self.response_body_stats = {}

    @classmethod
    def from_crawler(cls, crawler):
        middleware = cls()
        crawler.signals.connect(middleware.spider_opened, signal=signals.spider_opened)
        return middleware

    def spider_opened(self, spider):
        logger.info("ResponseBodyTracerMiddleware: Active")

    def process_response(self, request, response, spider):
        """Process response and log body reception details"""

        body_size = len(response.body)
        url = request.url

        # Get headers
        headers = {}
        for name, values in response.headers.items():
            header_name = name.decode('utf-8', errors='ignore')
            header_values = [v.decode('utf-8', errors='ignore') for v in values]
            headers[header_name] = header_values[0] if len(header_values) == 1 else header_values

        # Log transfer details
        content_length = headers.get('Content-Length', 'NOT SET')
        content_encoding = headers.get('Content-Encoding', 'NOT SET')
        transfer_encoding = headers.get('Transfer-Encoding', 'NOT SET')

        if body_size == 0:
            logger.error("=" * 80)
            logger.error("RESPONSE BODY TRACER: 0 BYTES DETECTED")
            logger.error("=" * 80)
            logger.error(f"URL: {url}")
            logger.error(f"HTTP Status: {response.status}")
            logger.error("")
            logger.error("Transfer Details:")
            logger.error(f"  Content-Length header: {content_length}")
            logger.error(f"  Content-Encoding: {content_encoding}")
            logger.error(f"  Transfer-Encoding: {transfer_encoding}")
            logger.error(f"  Actual bytes received: {body_size}")
            logger.error("")

            # Analyze discrepancy
            if content_length != 'NOT SET' and content_length != '0':
                try:
                    expected_size = int(content_length)
                    logger.error("❌ CONTENT LOSS DETECTED:")
                    logger.error(f"   Server said: {expected_size} bytes")
                    logger.error(f"   Scrapy received: {body_size} bytes")
                    logger.error(f"   Lost: {expected_size} bytes")
                    logger.error("")
                    logger.error("DIAGNOSIS:")
                    logger.error("  Content was stripped/filtered AFTER server sent it")
                    logger.error("  This indicates:")
                    logger.error("    - Transparent proxy filtering content")
                    logger.error("    - Network firewall/DPI modifying response")
                    logger.error("    - Twisted downloader error")
                    logger.error("")
                    logger.error("RECOMMENDATION:")
                    logger.error("  1. Check for transparent proxies on network")
                    logger.error("  2. Compare network traffic: tcpdump/Wireshark")
                    logger.error("  3. Test from different network")
                    logger.error("  4. Check Twisted download handler logs")

                except ValueError:
                    logger.error(f"Invalid Content-Length: {content_length}")

            # Check if compression failed
            if content_encoding != 'NOT SET' and content_encoding.lower() in ['gzip', 'deflate', 'br', 'brotli']:
                logger.error("⚠️  COMPRESSION ISSUE:")
                logger.error(f"   Content-Encoding: {content_encoding}")
                logger.error("   But body is empty!")
                logger.error("")
                logger.error("DIAGNOSIS:")
                logger.error("  Decompression may have failed")
                logger.error("  Twisted's compression middleware might have errors")
                logger.error("")
                logger.error("RECOMMENDATION:")
                logger.error("  1. Check Scrapy compression middleware logs")
                logger.error("  2. Try disabling compression in request")
                logger.error("  3. Verify Twisted can decompress this encoding")

            # Check chunked encoding issues
            if transfer_encoding != 'NOT SET' and 'chunked' in transfer_encoding.lower():
                logger.error("⚠️  CHUNKED TRANSFER ISSUE:")
                logger.error(f"   Transfer-Encoding: {transfer_encoding}")
                logger.error("   But received 0 bytes!")
                logger.error("")
                logger.error("DIAGNOSIS:")
                logger.error("  Chunked transfer encoding may have failed")
                logger.error("  Twisted may not be reading chunks correctly")
                logger.error("")
                logger.error("RECOMMENDATION:")
                logger.error("  1. Check if server sends invalid chunks")
                logger.error("  2. Verify Twisted HTTP/1.1 chunked reading")
                logger.error("  3. Try forcing HTTP/1.0 (no chunking)")

            # Check if body was actually sent
            if content_length == '0':
                logger.error("SERVER INTENTIONALLY SENT EMPTY RESPONSE:")
                logger.error("  Content-Length: 0 is explicit")
                logger.error("  Server detected and blocked the request")
                logger.error("")
                logger.error("RECOMMENDATION:")
                logger.error("  1. Check server logs for blocking reason")
                logger.error("  2. Verify User-Agent not blacklisted")
                logger.error("  3. Check if IP/network is blocked")
                logger.error("  4. Compare with working curl/urllib request")

            logger.error("=" * 80)

        return response

    def process_exception(self, request, exception, spider):
        """Log exceptions that might indicate content loss"""
        exception_str = str(exception).lower()

        # Check for decompression errors
        if 'decompress' in exception_str or 'zlib' in exception_str or 'gzip' in exception_str:
            logger.error("=" * 80)
            logger.error("DECOMPRESSION ERROR DETECTED")
            logger.error("=" * 80)
            logger.error(f"URL: {request.url}")
            logger.error(f"Exception: {exception}")
            logger.error("")
            logger.error("DIAGNOSIS:")
            logger.error("  Content decompression failed")
            logger.error("  This explains why body is 0 bytes")
            logger.error("")
            logger.error("POSSIBLE CAUSES:")
            logger.error("  1. Server sent invalid compressed data")
            logger.error("  2. Partial content received (connection interrupted)")
            logger.error("  3. Compression method mismatch")
            logger.error("  4. Proxy modified compressed data")
            logger.error("=" * 80)

        return None