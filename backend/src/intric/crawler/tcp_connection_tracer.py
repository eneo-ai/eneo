"""
TCP-level connection tracing to diagnose connection drops
This hooks into Twisted's connection lifecycle to see exactly HOW connections fail
"""
from scrapy import signals

from intric.main.logging import get_logger

logger = get_logger(__name__)


class TcpConnectionTracerExtension:
    """
    Extension to trace TCP connection lifecycle events
    Helps diagnose "Connection lost" errors by showing what happened at TCP level
    """

    def __init__(self, stats):
        self.stats = stats
        self.connections = {}

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls(crawler.stats)
        crawler.signals.connect(ext.request_reached_downloader, signal=signals.request_reached_downloader)
        crawler.signals.connect(ext.response_received, signal=signals.response_received)
        crawler.signals.connect(ext.request_dropped, signal=signals.request_dropped)
        logger.info("TcpConnectionTracerExtension: Monitoring TCP connection lifecycle")
        return ext

    def request_reached_downloader(self, request, spider):
        """Request reached downloader - TCP connection will be attempted"""
        logger.info(f"TCP TRACE: Request entering downloader: {request.url}")
        logger.info(f"   Will attempt TCP connection to: {request.url}")

    def response_received(self, response, request, spider):
        """Response received successfully"""
        logger.info(f"TCP TRACE: Response received successfully from: {request.url}")
        logger.info("   TCP connection worked, HTTP response received")

    def request_dropped(self, request, spider):
        """Request was dropped - connection failed"""
        logger.error(f"TCP TRACE: Request DROPPED: {request.url}")
        logger.error(f"   Reason: {request.meta.get('download_error', 'Unknown')}")


class ConnectionMonitoringMiddleware:
    """
    Middleware to add detailed connection-level logging
    Shows exactly when connections are established, used, and closed
    """

    def __init__(self):
        self.connection_events = {}

    @classmethod
    def from_crawler(cls, crawler):
        middleware = cls()
        crawler.signals.connect(middleware.spider_opened, signal=signals.spider_opened)
        return middleware

    def spider_opened(self, spider):
        logger.info("ConnectionMonitoringMiddleware: Active - will trace all connection events")

    def process_request(self, request, spider):
        """Log when request is about to use connection"""
        logger.info(f"CONNECTION: About to establish/reuse connection for {request.url}")
        return None

    def process_response(self, request, response, spider):
        """Log successful connection use"""
        logger.info(f"CONNECTION: Successfully used connection for {request.url}")
        return response

    def process_exception(self, request, exception, spider):
        """Log detailed connection failure info"""
        exception_str = str(exception)

        logger.error("=" * 80)
        logger.error("TCP CONNECTION FAILURE ANALYSIS")
        logger.error("=" * 80)

        # Analyze the Twisted failure
        if hasattr(exception, 'reasons'):
            logger.error(f"Failure reasons: {exception.reasons}")

            for reason in exception.reasons:
                logger.error(f"\nAnalyzing failure reason: {reason}")

                # Check what type of connection loss
                reason_str = str(reason).lower()

                if 'connectionlost' in reason_str:
                    logger.error("CONNECTION LOST DETAILS:")

                    if 'non-clean fashion' in reason_str:
                        logger.error("  Type: Non-clean connection loss")
                        logger.error("  Meaning: Server closed connection without proper TCP shutdown")
                        logger.error("  Likely: Server sent TCP RST (reset) instead of FIN")
                        logger.error("")
                        logger.error("WHY SERVER SENDS RST:")
                        logger.error("  1. Application-level rejection (WAF, bot detection)")
                        logger.error("  2. Server detected suspicious request pattern")
                        logger.error("  3. DPI system identified Twisted/Scrapy traffic signature")
                        logger.error("  4. Connection timeout on server side")
                        logger.error("")
                        logger.error("TWISTED TRAFFIC SIGNATURE:")
                        logger.error("  - Twisted sends requests slightly differently than curl/urllib")
                        logger.error("  - TCP packet timing and sizes differ")
                        logger.error("  - TLS ClientHello fingerprint may differ")
                        logger.error("  - HTTP request formatting may have subtle differences")

                    elif 'clean fashion' in reason_str:
                        logger.error("  Type: Clean connection close")
                        logger.error("  Meaning: Server sent proper TCP FIN")
                        logger.error("  This is normal connection close")

                if 'connectionrefused' in reason_str:
                    logger.error("CONNECTION REFUSED:")
                    logger.error("  Server actively refused connection")
                    logger.error("  Port may be closed or filtered")

                if 'timeout' in reason_str:
                    logger.error("CONNECTION TIMEOUT:")
                    logger.error("  Connection attempt timed out")
                    logger.error("  Server not responding or filtered")

        logger.error("")
        logger.error("RECOMMENDATION:")
        logger.error("  Since curl/wget/urllib all work, the issue is Twisted-specific")
        logger.error("  The server or network equipment is detecting Twisted's traffic")
        logger.error("")
        logger.error("POSSIBLE SOLUTIONS:")
        logger.error("  1. Capture tcpdump comparing urllib vs Scrapy requests")
        logger.error("  2. Check server logs for why it's dropping connections")
        logger.error("  3. Test with different downloader (use requests library instead of Twisted)")
        logger.error("  4. Contact network team about DPI/firewall rules")
        logger.error("=" * 80)

        return None