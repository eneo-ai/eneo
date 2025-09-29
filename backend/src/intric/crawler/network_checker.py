import asyncio
import socket
import ssl
from urllib.parse import urlparse
from typing import Dict, Any

from intric.main.logging import get_logger

logger = get_logger(__name__)


class NetworkChecker:
    """Pre-flight network connectivity checker for crawling"""

    @staticmethod
    async def check_connectivity(url: str) -> Dict[str, Any]:
        """
        Perform comprehensive network checks before crawling
        Returns dict with check results and diagnostics
        """
        logger.info(f"Starting pre-flight network checks for: {url}")

        parsed = urlparse(url)
        domain = parsed.netloc
        port = 443 if parsed.scheme == 'https' else 80

        results = {
            'url': url,
            'domain': domain,
            'port': port,
            'dns_resolution': False,
            'tcp_connection': False,
            'ssl_handshake': False,
            'http_response': False,
            'errors': [],
            'ip_address': None,
            'redirect_url': None
        }

        # 1. DNS Resolution Check
        try:
            logger.info(f"Checking DNS resolution for {domain}")
            ip_address = socket.gethostbyname(domain)
            results['dns_resolution'] = True
            results['ip_address'] = ip_address
            logger.info(f"DNS resolution successful: {domain} -> {ip_address}")
        except Exception as e:
            error_msg = f"DNS resolution failed: {str(e)}"
            logger.error(error_msg)
            results['errors'].append(error_msg)
            return results  # Can't continue without DNS

        # 2. TCP Connection Check
        try:
            logger.info(f"Testing TCP connection to {ip_address}:{port}")
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip_address, port),
                timeout=10.0
            )
            results['tcp_connection'] = True
            logger.info(f"TCP connection successful to {ip_address}:{port}")
            writer.close()
            await writer.wait_closed()
        except Exception as e:
            error_msg = f"TCP connection failed: {str(e)}"
            logger.error(error_msg)
            results['errors'].append(error_msg)
            return results  # Can't continue without TCP

        # 3. SSL Handshake Check (for HTTPS)
        if parsed.scheme == 'https':
            try:
                logger.info(f"Testing SSL handshake with {domain}")
                context = ssl.create_default_context()
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        ip_address, port,
                        ssl=context,
                        server_hostname=domain
                    ),
                    timeout=15.0
                )
                results['ssl_handshake'] = True
                logger.info(f"SSL handshake successful with {domain}")

                # Get SSL certificate info
                try:
                    ssl_object = writer.get_extra_info('ssl_object')
                    if ssl_object:
                        cert = ssl_object.getpeercert()
                        logger.info(f"SSL Certificate subject: {cert.get('subject', 'Unknown')}")
                        logger.info(f"SSL Certificate issuer: {cert.get('issuer', 'Unknown')}")
                        logger.info(f"SSL Certificate expires: {cert.get('notAfter', 'Unknown')}")
                except Exception as cert_e:
                    logger.warning(f"Could not retrieve SSL certificate details: {cert_e}")

                writer.close()
                await writer.wait_closed()
            except ssl.SSLError as ssl_e:
                error_msg = f"SSL handshake failed: {str(ssl_e)}"
                logger.error("🔒 SSL ERROR DETAILS:")
                logger.error(f"   - SSL Error: {ssl_e}")
                logger.error(f"   - SSL Error reason: {getattr(ssl_e, 'reason', 'Unknown')}")

                # Detailed SSL error analysis
                ssl_error_str = str(ssl_e).lower()
                if 'certificate verify failed' in ssl_error_str:
                    logger.error("   - Certificate verification failed")
                    if 'unknown ca' in ssl_error_str or 'unable to get local issuer certificate' in ssl_error_str:
                        logger.error("   - Unknown Certificate Authority (okänt CA)")
                        logger.error("   - The certificate is not trusted by this system")
                    elif 'hostname mismatch' in ssl_error_str:
                        logger.error("   - Certificate hostname mismatch")
                    elif 'certificate has expired' in ssl_error_str:
                        logger.error("   - Certificate has expired")
                elif 'handshake failure' in ssl_error_str:
                    logger.error("   - SSL handshake protocol failure")
                elif 'protocol version' in ssl_error_str:
                    logger.error("   - SSL/TLS protocol version mismatch")

                results['errors'].append(error_msg)
                return results  # Can't continue without SSL
            except Exception as e:
                error_msg = f"SSL handshake failed: {str(e)}"
                logger.error(f"🔒 SSL CONNECTION ERROR: {error_msg}")
                logger.error(f"   - Exception type: {type(e).__name__}")
                results['errors'].append(error_msg)
                return results  # Can't continue without SSL

        # 4. HTTP Response Check (simplified)
        try:
            logger.info(f"Testing basic HTTP response from {url}")
            # Use asyncio subprocess to call curl for a quick HTTP test
            proc = await asyncio.create_subprocess_exec(
                'curl', '-s', '-I', '--connect-timeout', '10', '--max-time', '15', url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                response_text = stdout.decode('utf-8', errors='ignore')
                logger.info(f"HTTP response received: {response_text[:200]}...")

                # Check for redirects
                if '301' in response_text or '302' in response_text:
                    for line in response_text.split('\n'):
                        if line.lower().startswith('location:'):
                            redirect_url = line.split(':', 1)[1].strip()
                            results['redirect_url'] = redirect_url
                            logger.info(f"Detected redirect to: {redirect_url}")
                            break

                results['http_response'] = True
                logger.info("HTTP response check successful")
            else:
                error_msg = f"HTTP request failed: {stderr.decode('utf-8', errors='ignore')}"
                logger.error(error_msg)
                results['errors'].append(error_msg)

        except Exception as e:
            error_msg = f"HTTP response check failed: {str(e)}"
            logger.error(error_msg)
            results['errors'].append(error_msg)

        # Summary
        success_count = sum([
            results['dns_resolution'],
            results['tcp_connection'],
            results['ssl_handshake'] if parsed.scheme == 'https' else True,
            results['http_response']
        ])
        total_checks = 4 if parsed.scheme == 'https' else 3

        logger.info(f"Pre-flight checks completed: {success_count}/{total_checks} passed")
        if results['errors']:
            logger.warning(f"Errors encountered: {results['errors']}")

        return results

    @staticmethod
    def log_network_diagnostics(results: Dict[str, Any]):
        """Log detailed network diagnostics"""
        logger.info("=== NETWORK DIAGNOSTICS ===")
        logger.info(f"Target: {results['url']}")
        logger.info(f"Domain: {results['domain']} -> {results.get('ip_address', 'FAILED')}")
        logger.info(f"DNS Resolution: {'✅' if results['dns_resolution'] else '❌'}")
        logger.info(f"TCP Connection: {'✅' if results['tcp_connection'] else '❌'}")
        if results['url'].startswith('https'):
            logger.info(f"SSL Handshake: {'✅' if results['ssl_handshake'] else '❌'}")
        logger.info(f"HTTP Response: {'✅' if results['http_response'] else '❌'}")

        if results.get('redirect_url'):
            logger.info(f"Redirect detected: {results['redirect_url']}")

        if results['errors']:
            logger.error("Errors detected:")
            for error in results['errors']:
                logger.error(f"  - {error}")

        logger.info("=== END DIAGNOSTICS ===")