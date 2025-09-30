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

        # CRITICAL: Log ALL response details to diagnose 0 bytes
        body_size = len(response.body)

        # Analyze response headers in detail
        headers_dict = {}
        for name, values in response.headers.items():
            header_name = name.decode('utf-8', errors='ignore')
            header_values = [v.decode('utf-8', errors='ignore') for v in values]
            headers_dict[header_name] = header_values[0] if len(header_values) == 1 else header_values

        logger.info("Response headers analysis:")
        logger.info(f"  Status: {response.status}")
        logger.info(f"  Content-Type: {headers_dict.get('Content-Type', 'NOT SET')}")
        logger.info(f"  Content-Length: {headers_dict.get('Content-Length', 'NOT SET')}")
        logger.info(f"  Content-Encoding: {headers_dict.get('Content-Encoding', 'NOT SET')}")
        logger.info(f"  Transfer-Encoding: {headers_dict.get('Transfer-Encoding', 'NOT SET')}")
        logger.info(f"  Server: {headers_dict.get('Server', 'NOT SET')}")
        logger.info(f"  Actual body size received: {body_size} bytes")

        # CRITICAL: Diagnose WHY 0 bytes
        if body_size == 0:
            logger.error("=" * 80)
            logger.error("DIAGNOSING ZERO-BYTE RESPONSE")
            logger.error("=" * 80)
            logger.error(f"URL: {request.url}")
            logger.error(f"Status: {response.status}")
            logger.error("")

            # Check Content-Length header
            content_length_header = headers_dict.get('Content-Length', 'NOT SET')
            if content_length_header == '0':
                logger.error("ROOT CAUSE: Server explicitly sent Content-Length: 0")
                logger.error("  This means the server intentionally returned empty content")
                logger.error("  Reasons:")
                logger.error("    - Server detected automated request (User-Agent, headers)")
                logger.error("    - Rate limiting or IP blocking (soft block)")
                logger.error("    - Resource moved/deleted but returned 200 instead of 404")
                logger.error("    - Authentication required but returned 200 instead of 401")
                logger.error("    - WAF/security filter stripping content")
            elif content_length_header == 'NOT SET':
                logger.error("ROOT CAUSE: No Content-Length header AND empty body")
                logger.error("  This is unusual - server should send Content-Length or use chunked encoding")
                logger.error("  Possible reasons:")
                logger.error("    - Connection closed prematurely")
                logger.error("    - Transfer-Encoding issue")
                logger.error("    - Proxy stripping content")
                logger.error("    - Network filtering/firewall modifying response")
            else:
                logger.error(f"ROOT CAUSE: Content-Length header says {content_length_header} bytes, but received 0")
                logger.error("  This means content was lost between server and Scrapy")
                logger.error("  Possible reasons:")
                logger.error("    - Transparent proxy intercepting and filtering")
                logger.error("    - Chunked transfer encoding error")
                logger.error("    - TLS/SSL layer dropping content")
                logger.error("    - Twisted downloader bug")

            # Check Transfer-Encoding
            transfer_encoding = headers_dict.get('Transfer-Encoding', 'NOT SET')
            if transfer_encoding != 'NOT SET':
                logger.error(f"  Transfer-Encoding: {transfer_encoding}")
                if 'chunked' in transfer_encoding.lower():
                    logger.error("  ⚠️  Chunked encoding used - Twisted may have issue reading chunks")

            # Check Content-Encoding (compression)
            content_encoding = headers_dict.get('Content-Encoding', 'NOT SET')
            if content_encoding != 'NOT SET':
                logger.error(f"  Content-Encoding: {content_encoding}")
                if content_encoding.lower() in ['gzip', 'deflate', 'br']:
                    logger.error(f"  ⚠️  Content is {content_encoding} compressed - decompression may have failed")

            # Check for blocking indicators in headers
            logger.error("")
            logger.error("Checking for blocking indicators in response headers:")

            # Check for WAF/security headers
            waf_headers = ['X-CDN', 'CF-RAY', 'X-Akamai', 'X-Cache', 'X-Served-By',
                          'X-Cloudflare-Request-Id', 'Server']
            found_waf = []
            for waf_header in waf_headers:
                if waf_header in headers_dict:
                    found_waf.append(f"{waf_header}: {headers_dict[waf_header]}")

            if found_waf:
                logger.error("  Found CDN/WAF headers (may indicate filtering):")
                for header in found_waf:
                    logger.error(f"    {header}")

            # Check for redirect loops or blocked content
            if response.status == 200 and body_size == 0:
                logger.error("")
                logger.error("  Status 200 with 0 bytes is HIGHLY SUSPICIOUS")
                logger.error("  This usually indicates:")
                logger.error("    1. Bot detection - server detected automation")
                logger.error("    2. Soft blocking - server responding but removing content")
                logger.error("    3. Content filtering - proxy/firewall stripping body")

            # Compare request headers vs typical browser
            logger.error("")
            logger.error("Request headers that may trigger filtering:")
            request_headers = {}
            for name, values in request.headers.items():
                header_name = name.decode('utf-8', errors='ignore')
                header_values = [v.decode('utf-8', errors='ignore') for v in values]
                request_headers[header_name] = header_values[0] if len(header_values) == 1 else header_values

            suspicious_headers = []
            if 'User-Agent' in request_headers:
                ua = request_headers['User-Agent']
                if 'scrapy' in ua.lower() or 'bot' in ua.lower() or 'spider' in ua.lower():
                    suspicious_headers.append(f"User-Agent contains bot indicator: {ua}")

            if 'Accept-Language' not in request_headers:
                suspicious_headers.append("Missing Accept-Language header (browsers always send this)")

            if 'Accept-Encoding' not in request_headers:
                suspicious_headers.append("Missing Accept-Encoding header")

            if suspicious_headers:
                logger.error("  Suspicious request headers:")
                for issue in suspicious_headers:
                    logger.error(f"    - {issue}")
            else:
                logger.error("  Request headers look reasonable")

            logger.error("")
            logger.error("=" * 80)

        elif body_size < 100:
            logger.warning(f"⚠️  Very small response: {body_size} bytes - may be error page")
            # Log the actual content to see what it is
            try:
                small_content = response.body.decode('utf-8', errors='ignore')
                logger.warning(f"Small content: {small_content}")
            except Exception:
                pass
        else:
            logger.info(f"✅ Received {body_size} bytes of content")

        # Check for redirects
        if response.status in [301, 302, 303, 307, 308]:
            location = response.headers.get(b'location', b'').decode('utf-8', errors='ignore')
            logger.info(f"REDIRECT: {response.status} from {request.url} to {location}")

        if response.status != 200:
            logger.warning(f"Non-200 response: {response.status}")

            # Specific status code explanations
            if response.status == 403:
                logger.error("403 Forbidden - Server explicitly rejecting the request")
                logger.error("   Likely causes: IP blocking, User-Agent filtering, or WAF")
            elif response.status == 401:
                logger.error("401 Unauthorized - Authentication required")
            elif response.status == 429:
                logger.error("429 Too Many Requests - Rate limiting")
            elif response.status >= 500:
                logger.error(f"{response.status} Server Error - Target server problem")

        # Log content preview if available
        if body_size > 0:
            body_preview = response.body[:200].decode('utf-8', errors='ignore')
            logger.info(f"Content preview: {body_preview}...")

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

        # Check for TLS/SSL-specific errors (CRITICAL for municipality networks)
        if 'ssl' in exception_str or 'certificate' in exception_str or 'tls' in exception_str:
            logger.error("=" * 80)
            logger.error("🔒 TLS/CERTIFICATE ERROR DETECTED")
            logger.error("=" * 80)

            if 'certificate verify failed' in exception_str:
                logger.error("ROOT CAUSE: TLS certificate verification failed")
                logger.error("")

                if 'unknown ca' in exception_str or 'unable to get local issuer certificate' in exception_str:
                    logger.error("SPECIFIC ISSUE: Unknown Certificate Authority (Okänt CA)")
                    logger.error("")
                    logger.error("EXPLANATION:")
                    logger.error("  - Twisted's OpenSSL cannot find the certificate authority that signed this cert")
                    logger.error("  - Python's ssl module (urllib) uses different CA bundle and DOES trust it")
                    logger.error("  - This is why urllib works but Scrapy/Twisted doesn't")
                    logger.error("")
                    logger.error("SOLUTIONS:")
                    logger.error("  1. Add CA certificate to system trust store in container")
                    logger.error("  2. Configure Twisted to use same CA bundle as Python ssl")
                    logger.error("  3. Disable certificate verification (NOT RECOMMENDED for production)")
                    logger.error("")
                    logger.error("FOR NETWORK TEAM:")
                    logger.error("  - Check if site uses internal/self-signed certificate")
                    logger.error("  - Verify certificate chain is complete")
                    logger.error("  - Compare: openssl s_client -connect {host}:443 -showcerts")

                elif 'hostname mismatch' in exception_str:
                    logger.error("SPECIFIC ISSUE: Certificate hostname mismatch")
                    logger.error("  - Certificate doesn't match the domain being accessed")

                elif 'certificate has expired' in exception_str:
                    logger.error("SPECIFIC ISSUE: Certificate has expired")
                    logger.error("  - Server's TLS certificate is no longer valid")

            elif 'handshake' in exception_str:
                logger.error("ROOT CAUSE: TLS handshake failed")
                logger.error("  - Connection established but TLS negotiation failed")
                logger.error("  - May indicate protocol version mismatch or cipher incompatibility")

            logger.error(f"Full exception: {exception}")
            logger.error("=" * 80)

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