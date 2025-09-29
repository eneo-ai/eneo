import time
from scrapy import signals
from scrapy.http import Request, Response

from intric.main.logging import get_logger

logger = get_logger(__name__)


class DebugLoggingMiddleware:
    """Middleware to log every request and response for debugging with comprehensive error analysis"""

    def __init__(self):
        logger.info("DebugLoggingMiddleware initialized")
        self.request_timestamps = {}  # Track request timing

    @classmethod
    def from_crawler(cls, crawler):
        o = cls()
        crawler.signals.connect(o.spider_opened, signal=signals.spider_opened)
        return o

    def spider_opened(self, spider):
        logger.info(f"DebugLoggingMiddleware: Spider {spider.name} opened")

    def process_request(self, request: Request, spider):
        # Record request start time
        request_id = f"{request.url}#{time.time()}"
        self.request_timestamps[request_id] = {
            'start': time.time(),
            'url': request.url
        }

        logger.info(f"REQUEST: {request.method} {request.url}")
        logger.info(f"REQUEST ID: {request_id}")

        # Log headers in a more readable format
        headers_dict = {}
        for name, values in request.headers.items():
            header_name = name.decode('utf-8')
            header_values = [v.decode('utf-8') for v in values]
            headers_dict[header_name] = header_values[0] if len(header_values) == 1 else header_values

        logger.info(f"Request headers: {headers_dict}")
        logger.debug(f"Request meta: {request.meta}")

        # Log detailed request composition
        logger.debug("Request details:")
        logger.debug(f"  - URL: {request.url}")
        logger.debug(f"  - Method: {request.method}")
        logger.debug(f"  - Headers count: {len(headers_dict)}")
        logger.debug(f"  - Meta keys: {list(request.meta.keys())}")
        logger.debug(f"  - Body length: {len(request.body) if request.body else 0}")

        # Store request ID in meta for correlation
        request.meta['debug_request_id'] = request_id

        return None  # Continue processing

    def process_response(self, request: Request, response: Response, spider):
        # Calculate response timing
        request_id = request.meta.get('debug_request_id')
        response_time_ms = 0
        if request_id and request_id in self.request_timestamps:
            start_time = self.request_timestamps[request_id]['start']
            response_time_ms = (time.time() - start_time) * 1000
            logger.info(f"RESPONSE TIMING: {response_time_ms:.2f}ms for {request.url}")
            # Clean up timestamp tracking
            del self.request_timestamps[request_id]

        logger.info(f"RESPONSE: {response.status} for {request.url}")
        logger.info(f"Response headers: {dict(response.headers)}")
        logger.info(f"Response body length: {len(response.body)} bytes")

        # Check for redirects
        if response.status in [301, 302, 303, 307, 308]:
            location = response.headers.get(b'location', b'').decode('utf-8', errors='ignore')
            logger.info(f"REDIRECT: {response.status} from {request.url} to {location}")

        if response.status != 200:
            logger.warning(f"Non-200 response: {response.status} {response.reason}")

        if len(response.body) == 0:
            logger.warning(f"Empty response body for {request.url}")
        else:
            # Log a snippet of the response body
            body_preview = response.body[:200].decode('utf-8', errors='ignore')
            logger.info(f"Response body preview: {body_preview}...")

        return response

    def process_exception(self, request: Request, exception, spider):
        # Calculate timing if available
        request_id = request.meta.get('debug_request_id')
        elapsed_ms = 0
        if request_id and request_id in self.request_timestamps:
            start_time = self.request_timestamps[request_id]['start']
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(f"EXCEPTION TIMING: {elapsed_ms:.2f}ms elapsed before failure")
            # Clean up timestamp tracking
            del self.request_timestamps[request_id]

        logger.error("=" * 60)
        logger.error("COMPREHENSIVE REQUEST EXCEPTION ANALYSIS")
        logger.error("=" * 60)
        logger.error(f"REQUEST EXCEPTION: {exception} for {request.url}")
        logger.error(f"Exception type: {type(exception).__name__}")
        logger.error(f"Exception module: {type(exception).__module__}")
        logger.error(f"Full exception details: {repr(exception)}")

        # Extract more detailed error information
        try:
            if hasattr(exception, 'args') and exception.args:
                logger.error(f"Exception args: {exception.args}")
            if hasattr(exception, 'errno'):
                logger.error(f"Error number: {exception.errno}")
            if hasattr(exception, 'strerror'):
                logger.error(f"Error string: {exception.strerror}")
            if hasattr(exception, 'reason'):
                logger.error(f"Exception reason: {exception.reason}")
        except Exception as e:
            logger.debug(f"Could not extract additional exception details: {e}")

        # Log request details at time of failure
        logger.error("REQUEST STATE AT FAILURE:")
        logger.error(f"   - URL: {request.url}")
        logger.error(f"   - Method: {request.method}")
        logger.error(f"   - Headers sent: {dict(request.headers)}")
        logger.error(f"   - Meta data: {dict(request.meta)}")
        logger.error(f"   - Time elapsed: {elapsed_ms:.2f}ms")

        # Detailed exception analysis
        exception_name = type(exception).__name__
        exception_str = str(exception).lower()

        # Check for TLS/SSL-specific errors
        if 'ssl' in exception_str or 'certificate' in exception_str or 'tls' in exception_str:
            logger.error("🔒 TLS/CERTIFICATE ERROR DETECTED:")
            if 'certificate verify failed' in exception_str:
                logger.error("   - TLS certificate verification failed")
                if 'unknown ca' in exception_str or 'unable to get local issuer certificate' in exception_str:
                    logger.error("   - Unknown Certificate Authority (okänt CA)")
                    logger.error("   - Certificate is not trusted by the system")
                elif 'hostname mismatch' in exception_str:
                    logger.error("   - TLS certificate hostname mismatch")
                elif 'certificate has expired' in exception_str:
                    logger.error("   - TLS certificate has expired")
            elif 'handshake' in exception_str:
                logger.error("   - TLS handshake failed")
            elif 'tls' in exception_str:
                logger.error("   - TLS protocol error")
            logger.error(f"   - Full TLS error: {exception}")

        # Connection-level analysis
        elif exception_name in ['ConnectionLost', 'ResponseNeverReceived']:
            logger.error("🔌 CONNECTION LOST ANALYSIS:")
            logger.error("   - TCP connection was established but then lost")

            if elapsed_ms < 1000:  # Less than 1 second
                logger.error("   - Connection lost immediately after establishment")
                logger.error("   - This suggests server-side rejection or filtering")
            elif 1000 <= elapsed_ms < 15000:  # 1-15 seconds
                logger.error(f"   - Connection lost after {elapsed_ms/1000:.1f}s")
                logger.error("   - This suggests request processing started but was interrupted")
            else:  # More than 15 seconds
                logger.error(f"   - Connection lost after {elapsed_ms/1000:.1f}s")
                logger.error("   - This suggests timeout or deliberate connection dropping")

            # Analyze connection loss patterns
            if 'Connection lost' in str(exception):
                logger.error("   - Twisted ConnectionLost: Server closed connection unexpectedly")
            elif 'ResponseNeverReceived' in str(exception):
                logger.error("   - No HTTP response received despite connection")
                logger.error("   - Server may be tarpitting or filtering requests")

        # Timeout analysis
        elif exception_name == 'TimeoutError':
            logger.error("⏰ TIMEOUT ERROR ANALYSIS:")
            logger.error(f"   - Request timed out after {elapsed_ms/1000:.1f}s")

            timeout_value = request.meta.get('download_timeout', 'unknown')
            logger.error(f"   - Configured timeout: {timeout_value}s")

            # Analyze timeout patterns to detect bot detection
            if 'User timeout caused connection failure' in str(exception):
                logger.error("🚫 CONFIRMED: Server is tarpitting (accepting connection but not responding)")
                logger.error("   - Server accepts TCP connection but deliberately stalls HTTP response")
                logger.error("   - This indicates sophisticated bot detection beyond simple blocking")
                logger.error("   - The server is likely analyzing request patterns and stalling suspected bots")
            elif 'took longer than' in str(exception):
                logger.error("   - Request exceeded maximum allowed time")
                logger.error("   - This suggests the server is deliberately ignoring the request")

            # Check if this is consistent tarpitting
            if elapsed_ms > 15000:  # More than 15 seconds
                logger.error("   - LIKELY TARPITTING: Consistent long delays suggest deliberate stalling")

        # DNS and connection errors
        elif exception_name in ['DNSLookupError', 'ConnectionRefusedError']:
            logger.error("🌐 NETWORK CONNECTIVITY ERROR:")
            logger.error(f"   - Basic network connectivity issue: {exception}")

            if exception_name == 'DNSLookupError':
                logger.error("   - Could not resolve hostname to IP address")
                logger.error("   - Check DNS configuration and network connectivity")
            elif exception_name == 'ConnectionRefusedError':
                logger.error("   - Target server refused the connection")
                logger.error("   - Port may be closed or server may be down")

        # Twisted-specific errors
        elif 'twisted.internet.error' in str(type(exception)):
            logger.error("🔌 TWISTED NETWORK ERROR:")
            logger.error(f"   - Low-level Twisted networking error: {exception}")
            logger.error("   - This indicates issues at the socket/transport layer")

        # Generic analysis for other errors
        else:
            logger.error("❓ UNKNOWN EXCEPTION TYPE:")
            logger.error(f"   - Exception class: {type(exception)}")
            logger.error(f"   - Exception hierarchy: {[cls.__name__ for cls in type(exception).__mro__]}")

        # Pattern-based issue detection
        logger.error("PATTERN ANALYSIS:")

        # Check for specific error messages that indicate network issues
        error_patterns = {
            'connection reset': "Network connection was reset - may indicate firewall or proxy interference",
            'connection refused': "Server actively refused connection - port may be closed",
            'network unreachable': "Network routing issue - check connectivity",
            'host unreachable': "Cannot reach target host - routing or firewall issue",
            'operation timed out': "Operation exceeded time limit - may indicate filtering",
            'permission denied': "Network permission issue - may indicate security restrictions"
        }

        for pattern, description in error_patterns.items():
            if pattern in exception_str:
                logger.error(f"   - Detected '{pattern}': {description}")

        # Municipality-specific analysis
        logger.error("MUNICIPALITY NETWORK CONSIDERATIONS:")
        logger.error("   - Municipality networks often have:")
        logger.error("     • Transparent proxies that modify requests")
        logger.error("     • Deep packet inspection (DPI) systems")
        logger.error("     • Firewall rules blocking certain user agents")
        logger.error("     • Quality of Service (QoS) throttling")
        logger.error("     • Content filtering systems")
        logger.error("   - Compare with hotspot success to identify differences")

        logger.error("NEXT STEPS:")
        logger.error("   1. Run comprehensive network diagnostics")
        logger.error("   2. Compare request methods (curl, wget, urllib)")
        logger.error("   3. Analyze TCP connection patterns")
        logger.error("   4. Check for transparent proxy or firewall interference")

        logger.error("=" * 60)

        return None  # Continue with default exception handling