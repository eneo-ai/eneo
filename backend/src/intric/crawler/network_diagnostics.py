import asyncio
import os
import socket
import time
from typing import Dict, Any
from urllib.parse import urlparse
import ssl

from intric.main.logging import get_logger

logger = get_logger(__name__)


class NetworkDiagnostics:
    """Comprehensive network diagnostics to identify connection differences between networks"""

    @staticmethod
    async def capture_complete_network_environment() -> Dict[str, Any]:
        """Capture complete network environment details"""
        logger.info("=== CAPTURING COMPLETE NETWORK ENVIRONMENT ===")

        env_data = {
            'timestamp': time.time(),
            'environment_variables': {},
            'network_interfaces': {},
            'dns_config': {},
            'routing_table': {},
            'tcp_parameters': {},
            'external_ip': None,
            'proxy_detection': {},
            'mtu_analysis': {},
        }

        # 1. Environment Variables (especially proxy settings)
        logger.info("Capturing environment variables...")
        proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'FTP_PROXY', 'NO_PROXY', 'ALL_PROXY', 'SOCKS_PROXY']
        proxy_vars_lower = [var.lower() for var in proxy_vars]

        for var in proxy_vars + proxy_vars_lower:
            if var in os.environ:
                env_data['environment_variables'][var] = os.environ[var]
                logger.info(f"Found proxy env var: {var}={os.environ[var]}")

        # Also capture other relevant network env vars
        other_vars = ['PATH', 'USER', 'HOME', 'HOSTNAME', 'container']
        for var in other_vars:
            if var in os.environ:
                env_data['environment_variables'][var] = os.environ[var]

        # 2. Network Interfaces with MTU
        logger.info("Analyzing network interfaces...")
        try:
            result = await asyncio.create_subprocess_exec(
                'ip', 'addr', 'show',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            if result.returncode == 0:
                interfaces_output = stdout.decode('utf-8')
                env_data['network_interfaces']['ip_addr'] = interfaces_output
                logger.info("Network interfaces captured")

                # Parse MTU values
                for line in interfaces_output.split('\n'):
                    if 'mtu' in line.lower():
                        logger.info(f"MTU info: {line.strip()}")
            else:
                logger.warning(f"Failed to get network interfaces: {stderr.decode()}")
        except Exception as e:
            logger.error(f"Error capturing network interfaces: {e}")

        # 3. DNS Configuration
        logger.info("Capturing DNS configuration...")
        try:
            if os.path.exists('/etc/resolv.conf'):
                with open('/etc/resolv.conf', 'r') as f:
                    dns_config = f.read()
                    env_data['dns_config']['resolv_conf'] = dns_config
                    logger.info(f"DNS config: {dns_config}")

            # Also get system DNS via nslookup if available
            try:
                result = await asyncio.create_subprocess_exec(
                    'nslookup', 'google.com',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await result.communicate()
                if result.returncode == 0:
                    env_data['dns_config']['nslookup_test'] = stdout.decode('utf-8')
            except:
                pass

        except Exception as e:
            logger.error(f"Error capturing DNS config: {e}")

        # 4. Routing Table
        logger.info("Capturing routing table...")
        try:
            result = await asyncio.create_subprocess_exec(
                'ip', 'route', 'show',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            if result.returncode == 0:
                routes = stdout.decode('utf-8')
                env_data['routing_table']['routes'] = routes
                logger.info(f"Routing table: {routes}")
            else:
                logger.warning(f"Failed to get routing table: {stderr.decode()}")
        except Exception as e:
            logger.error(f"Error capturing routing table: {e}")

        # 5. TCP Parameters
        logger.info("Capturing TCP parameters...")
        tcp_params = [
            'tcp_congestion_control', 'tcp_window_scaling', 'tcp_timestamps',
            'tcp_sack', 'tcp_fack', 'tcp_keepalive_time', 'tcp_keepalive_intvl',
            'tcp_keepalive_probes', 'tcp_retries1', 'tcp_retries2', 'tcp_syn_retries',
            'tcp_fin_timeout', 'tcp_max_syn_backlog', 'tcp_rmem', 'tcp_wmem'
        ]

        for param in tcp_params:
            try:
                param_path = f'/proc/sys/net/ipv4/{param}'
                if os.path.exists(param_path):
                    with open(param_path, 'r') as f:
                        value = f.read().strip()
                        env_data['tcp_parameters'][param] = value
                        logger.debug(f"TCP param {param}: {value}")
            except Exception as e:
                logger.debug(f"Could not read TCP param {param}: {e}")

        # 6. External IP Address
        logger.info("Detecting external IP address...")
        try:
            # Test multiple IP detection services
            ip_services = [
                'https://api.ipify.org',
                'https://ifconfig.me/ip',
                'https://icanhazip.com'
            ]

            for service in ip_services:
                try:
                    result = await asyncio.create_subprocess_exec(
                        'curl', '-s', '--connect-timeout', '5', '--max-time', '10', service,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, stderr = await result.communicate()
                    if result.returncode == 0:
                        external_ip = stdout.decode().strip()
                        env_data['external_ip'] = external_ip
                        logger.info(f"External IP (via {service}): {external_ip}")
                        break
                except Exception as e:
                    logger.debug(f"Failed to get IP from {service}: {e}")
                    continue
        except Exception as e:
            logger.warning(f"Could not determine external IP: {e}")

        # 7. Proxy Detection
        logger.info("Testing for transparent proxies...")
        try:
            # Test if we're behind a transparent proxy
            test_urls = [
                'http://httpbin.org/ip',
                'http://proxy.example.com',  # Common transparent proxy test
            ]

            for url in test_urls:
                try:
                    result = await asyncio.create_subprocess_exec(
                        'curl', '-s', '--connect-timeout', '3', '--max-time', '5', url,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, stderr = await result.communicate()
                    env_data['proxy_detection'][url] = {
                        'returncode': result.returncode,
                        'stdout': stdout.decode()[:200],  # Limit output
                        'stderr': stderr.decode()[:200],
                    }
                except Exception as e:
                    env_data['proxy_detection'][url] = {'error': str(e)}
        except Exception as e:
            logger.warning(f"Proxy detection failed: {e}")

        # 8. MTU Path Discovery
        logger.info("Testing MTU path discovery...")
        try:
            # Test different packet sizes to detect MTU issues
            test_host = 'google.com'
            mtu_sizes = [1472, 1500, 1400, 1200, 1000, 576]  # Common MTU sizes minus IP/ICMP headers

            for size in mtu_sizes:
                try:
                    result = await asyncio.create_subprocess_exec(
                        'ping', '-c', '1', '-M', 'do', '-s', str(size), test_host,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, stderr = await result.communicate()
                    env_data['mtu_analysis'][str(size)] = {
                        'success': result.returncode == 0,
                        'output': stdout.decode() if result.returncode == 0 else stderr.decode()
                    }
                    if result.returncode == 0:
                        logger.info(f"MTU test: {size} bytes - SUCCESS")
                    else:
                        logger.info(f"MTU test: {size} bytes - FAILED")
                except Exception as e:
                    env_data['mtu_analysis'][str(size)] = {'error': str(e)}
        except Exception as e:
            logger.warning(f"MTU analysis failed: {e}")

        logger.info("=== NETWORK ENVIRONMENT CAPTURE COMPLETE ===")
        return env_data

    @staticmethod
    async def analyze_tcp_connection(host: str, port: int, timeout: float = 10.0) -> Dict[str, Any]:
        """Detailed TCP connection analysis"""
        logger.info(f"=== TCP CONNECTION ANALYSIS: {host}:{port} ===")

        analysis = {
            'host': host,
            'port': port,
            'timestamps': {},
            'socket_options': {},
            'connection_details': {},
            'timing_breakdown': {},
            'errors': []
        }

        start_time = time.time()
        analysis['timestamps']['start'] = start_time

        try:
            # 1. DNS Resolution Timing
            logger.info("Starting DNS resolution...")
            dns_start = time.time()

            try:
                addr_info = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
                dns_end = time.time()
                analysis['timestamps']['dns_resolved'] = dns_end
                analysis['timing_breakdown']['dns_resolution_ms'] = (dns_end - dns_start) * 1000
                analysis['connection_details']['resolved_addresses'] = [
                    {'family': ai[0], 'address': ai[4][0]} for ai in addr_info
                ]
                logger.info(f"DNS resolution took {analysis['timing_breakdown']['dns_resolution_ms']:.2f}ms")

                # Use first IPv4 address if available, otherwise first address
                target_addr = None
                for ai in addr_info:
                    if ai[0] == socket.AF_INET:  # Prefer IPv4
                        target_addr = ai[4][0]
                        break
                if not target_addr:
                    target_addr = addr_info[0][4][0]

                analysis['connection_details']['target_address'] = target_addr

            except Exception as e:
                analysis['errors'].append(f"DNS resolution failed: {e}")
                logger.error(f"DNS resolution failed: {e}")
                return analysis

            # 2. TCP Connection with detailed timing
            logger.info(f"Starting TCP connection to {target_addr}:{port}...")
            tcp_start = time.time()

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)

            # Capture initial socket options
            try:
                initial_opts = {}
                for opt_name, opt_const in [
                    ('SO_SNDBUF', socket.SO_SNDBUF),
                    ('SO_RCVBUF', socket.SO_RCVBUF),
                    ('SO_KEEPALIVE', socket.SO_KEEPALIVE),
                    ('TCP_NODELAY', socket.TCP_NODELAY),
                ]:
                    try:
                        initial_opts[opt_name] = sock.getsockopt(socket.SOL_SOCKET if 'SO_' in opt_name else socket.IPPROTO_TCP, opt_const)
                    except:
                        pass
                analysis['socket_options']['initial'] = initial_opts
                logger.debug(f"Initial socket options: {initial_opts}")
            except Exception as e:
                logger.debug(f"Could not capture initial socket options: {e}")

            try:
                # Attempt connection
                sock.connect((target_addr, port))
                tcp_end = time.time()
                analysis['timestamps']['tcp_connected'] = tcp_end
                analysis['timing_breakdown']['tcp_connect_ms'] = (tcp_end - tcp_start) * 1000
                logger.info(f"TCP connection established in {analysis['timing_breakdown']['tcp_connect_ms']:.2f}ms")

                # Capture post-connection socket options
                try:
                    post_opts = {}
                    for opt_name, opt_const in [
                        ('SO_SNDBUF', socket.SO_SNDBUF),
                        ('SO_RCVBUF', socket.SO_RCVBUF),
                        ('SO_KEEPALIVE', socket.SO_KEEPALIVE),
                        ('TCP_NODELAY', socket.TCP_NODELAY),
                    ]:
                        try:
                            post_opts[opt_name] = sock.getsockopt(socket.SOL_SOCKET if 'SO_' in opt_name else socket.IPPROTO_TCP, opt_const)
                        except:
                            pass
                    analysis['socket_options']['post_connect'] = post_opts
                    logger.debug(f"Post-connection socket options: {post_opts}")
                except Exception as e:
                    logger.debug(f"Could not capture post-connection socket options: {e}")

                # Get socket peer information
                try:
                    peer_info = sock.getpeername()
                    local_info = sock.getsockname()
                    analysis['connection_details']['peer_address'] = peer_info
                    analysis['connection_details']['local_address'] = local_info
                    logger.info(f"Connection: {local_info} -> {peer_info}")
                except Exception as e:
                    logger.debug(f"Could not get socket peer info: {e}")

                # 3. TLS Handshake if HTTPS
                if port == 443:
                    logger.info("Starting TLS handshake...")
                    tls_start = time.time()

                    try:
                        context = ssl.create_default_context()
                        tls_sock = context.wrap_socket(sock, server_hostname=host)
                        tls_end = time.time()
                        analysis['timestamps']['tls_connected'] = tls_end
                        analysis['timing_breakdown']['tls_handshake_ms'] = (tls_end - tls_start) * 1000
                        logger.info(f"TLS handshake completed in {analysis['timing_breakdown']['tls_handshake_ms']:.2f}ms")

                        # Get TLS details
                        try:
                            tls_info = {
                                'version': tls_sock.version(),
                                'cipher': tls_sock.cipher(),
                                'certificate': tls_sock.getpeercert()
                            }
                            analysis['connection_details']['tls'] = tls_info
                            logger.info(f"TLS version: {tls_info['version']}, Cipher: {tls_info['cipher']}")
                        except Exception as e:
                            logger.debug(f"Could not get TLS details: {e}")

                        sock = tls_sock  # Use TLS socket for further operations

                    except Exception as e:
                        analysis['errors'].append(f"TLS handshake failed: {e}")
                        logger.error(f"TLS handshake failed: {e}")
                        return analysis

                # 4. Test basic HTTP request
                logger.info("Testing basic HTTP request...")
                http_start = time.time()

                try:
                    # Send minimal HTTP request
                    http_request = f"GET / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
                    sock.send(http_request.encode())

                    # Read response
                    response = sock.recv(1024).decode('utf-8', errors='ignore')
                    http_end = time.time()

                    analysis['timestamps']['http_response'] = http_end
                    analysis['timing_breakdown']['http_response_ms'] = (http_end - http_start) * 1000
                    analysis['connection_details']['http_response_preview'] = response[:200]
                    logger.info(f"HTTP response received in {analysis['timing_breakdown']['http_response_ms']:.2f}ms")
                    logger.debug(f"Response preview: {response[:100]}")

                except Exception as e:
                    analysis['errors'].append(f"HTTP request failed: {e}")
                    logger.error(f"HTTP request failed: {e}")

                sock.close()

            except Exception as e:
                analysis['errors'].append(f"TCP connection failed: {e}")
                logger.error(f"TCP connection failed: {e}")
                sock.close()
                return analysis

        except Exception as e:
            analysis['errors'].append(f"Connection analysis failed: {e}")
            logger.error(f"Connection analysis failed: {e}")

        end_time = time.time()
        analysis['timestamps']['end'] = end_time
        analysis['timing_breakdown']['total_ms'] = (end_time - start_time) * 1000

        logger.info(f"=== TCP ANALYSIS COMPLETE: Total time {analysis['timing_breakdown']['total_ms']:.2f}ms ===")
        return analysis

    @staticmethod
    async def compare_request_methods(url: str) -> Dict[str, Any]:
        """Test the same URL with multiple request methods"""
        logger.info(f"=== COMPARING REQUEST METHODS FOR: {url} ===")

        parsed_url = urlparse(url)
        results = {
            'url': url,
            'methods': {},
            'comparison': {}
        }

        # 1. Raw socket request
        logger.info("Testing raw socket request...")
        try:
            start_time = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(30)

            if parsed_url.scheme == 'https':
                context = ssl.create_default_context()
                sock = context.wrap_socket(sock, server_hostname=parsed_url.hostname)

            port = parsed_url.port or (443 if parsed_url.scheme == 'https' else 80)
            sock.connect((parsed_url.hostname, port))

            # Send minimal HTTP request
            path = parsed_url.path or '/'
            if parsed_url.query:
                path += '?' + parsed_url.query

            request = f"GET {path} HTTP/1.1\r\nHost: {parsed_url.hostname}\r\nConnection: close\r\n\r\n"
            sock.send(request.encode())

            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if len(response) > 10000:  # Limit response size
                    break

            sock.close()
            end_time = time.time()

            results['methods']['raw_socket'] = {
                'success': True,
                'time_ms': (end_time - start_time) * 1000,
                'response_size': len(response),
                'status_line': response.split(b'\r\n')[0].decode('utf-8', errors='ignore'),
                'headers_count': len([line for line in response.split(b'\r\n\r\n')[0].split(b'\r\n') if line])
            }
            logger.info(f"Raw socket: SUCCESS in {results['methods']['raw_socket']['time_ms']:.2f}ms")

        except Exception as e:
            results['methods']['raw_socket'] = {
                'success': False,
                'error': str(e),
                'time_ms': 0
            }
            logger.error(f"Raw socket: FAILED - {e}")

        # 2. cURL request
        logger.info("Testing cURL request...")
        try:
            start_time = time.time()
            result = await asyncio.create_subprocess_exec(
                'curl', '-vvv', '--connect-timeout', '30', '--max-time', '60',
                '--trace-ascii', '/dev/stderr', url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            end_time = time.time()

            results['methods']['curl'] = {
                'success': result.returncode == 0,
                'time_ms': (end_time - start_time) * 1000,
                'response_size': len(stdout),
                'returncode': result.returncode,
                'stderr_preview': stderr.decode('utf-8', errors='ignore')[:500],
                'stdout_preview': stdout.decode('utf-8', errors='ignore')[:200]
            }

            if result.returncode == 0:
                logger.info(f"cURL: SUCCESS in {results['methods']['curl']['time_ms']:.2f}ms")
            else:
                logger.error(f"cURL: FAILED with return code {result.returncode}")

        except Exception as e:
            results['methods']['curl'] = {
                'success': False,
                'error': str(e),
                'time_ms': 0
            }
            logger.error(f"cURL: FAILED - {e}")

        # 3. wget request
        logger.info("Testing wget request...")
        try:
            start_time = time.time()
            result = await asyncio.create_subprocess_exec(
                'wget', '--debug', '--timeout=30', '--tries=1', '-O', '/dev/stdout', url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            end_time = time.time()

            results['methods']['wget'] = {
                'success': result.returncode == 0,
                'time_ms': (end_time - start_time) * 1000,
                'response_size': len(stdout),
                'returncode': result.returncode,
                'stderr_preview': stderr.decode('utf-8', errors='ignore')[:500],
                'stdout_preview': stdout.decode('utf-8', errors='ignore')[:200]
            }

            if result.returncode == 0:
                logger.info(f"wget: SUCCESS in {results['methods']['wget']['time_ms']:.2f}ms")
            else:
                logger.error(f"wget: FAILED with return code {result.returncode}")

        except Exception as e:
            results['methods']['wget'] = {
                'success': False,
                'error': str(e),
                'time_ms': 0
            }
            logger.error(f"wget: FAILED - {e}")

        # 4. Python urllib request
        logger.info("Testing Python urllib request...")
        try:
            import urllib.request
            import urllib.error

            start_time = time.time()

            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0 (compatible; NetworkDiagnostics/1.0)')

            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read(10000)  # Limit to 10KB
                end_time = time.time()

                results['methods']['urllib'] = {
                    'success': True,
                    'time_ms': (end_time - start_time) * 1000,
                    'response_size': len(data),
                    'status_code': response.getcode(),
                    'headers_count': len(response.headers),
                    'content_preview': data[:200].decode('utf-8', errors='ignore')
                }
                logger.info(f"urllib: SUCCESS in {results['methods']['urllib']['time_ms']:.2f}ms")

        except Exception as e:
            results['methods']['urllib'] = {
                'success': False,
                'error': str(e),
                'time_ms': 0
            }
            logger.error(f"urllib: FAILED - {e}")

        # Comparison analysis
        successful_methods = [name for name, data in results['methods'].items() if data.get('success')]
        failed_methods = [name for name, data in results['methods'].items() if not data.get('success')]

        results['comparison'] = {
            'successful_methods': successful_methods,
            'failed_methods': failed_methods,
            'success_rate': len(successful_methods) / len(results['methods']),
            'fastest_method': None,
            'timing_analysis': {}
        }

        # Find fastest successful method
        if successful_methods:
            fastest = min(successful_methods, key=lambda m: results['methods'][m]['time_ms'])
            results['comparison']['fastest_method'] = {
                'method': fastest,
                'time_ms': results['methods'][fastest]['time_ms']
            }

        # Timing analysis
        for method, data in results['methods'].items():
            if data.get('success'):
                results['comparison']['timing_analysis'][method] = {
                    'time_ms': data['time_ms'],
                    'relative_speed': data['time_ms'] / min(results['methods'][m]['time_ms'] for m in successful_methods) if successful_methods else 1
                }

        logger.info(f"Request method comparison complete: {len(successful_methods)}/{len(results['methods'])} successful")
        logger.info("=== REQUEST METHODS COMPARISON COMPLETE ===")

        return results

    @staticmethod
    def log_comprehensive_diagnostics(env_data: Dict, tcp_analysis: Dict, request_comparison: Dict):
        """Log all diagnostics in a structured format"""
        logger.info("=" * 80)
        logger.info("COMPREHENSIVE NETWORK DIAGNOSTICS SUMMARY")
        logger.info("=" * 80)

        # Environment Summary
        logger.info("NETWORK ENVIRONMENT:")
        logger.info(f"  External IP: {env_data.get('external_ip', 'Unknown')}")
        logger.info(f"  Proxy variables: {len(env_data.get('environment_variables', {}))}")
        logger.info(f"  DNS servers: {len(env_data.get('dns_config', {}))}")
        logger.info(f"  TCP parameters captured: {len(env_data.get('tcp_parameters', {}))}")

        # Connection Summary
        logger.info("TCP CONNECTION:")
        if tcp_analysis.get('timing_breakdown'):
            timing = tcp_analysis['timing_breakdown']
            logger.info(f"  DNS Resolution: {timing.get('dns_resolution_ms', 0):.2f}ms")
            logger.info(f"  TCP Connect: {timing.get('tcp_connect_ms', 0):.2f}ms")
            logger.info(f"  TLS Handshake: {timing.get('tls_handshake_ms', 0):.2f}ms")
            logger.info(f"  HTTP Response: {timing.get('http_response_ms', 0):.2f}ms")
            logger.info(f"  Total Time: {timing.get('total_ms', 0):.2f}ms")

        # Request Methods Summary
        logger.info("REQUEST METHODS:")
        if request_comparison.get('methods'):
            for method, result in request_comparison['methods'].items():
                status = "✅ SUCCESS" if result.get('success') else "❌ FAILED"
                time_ms = result.get('time_ms', 0)
                logger.info(f"  {method.upper()}: {status} ({time_ms:.2f}ms)")

        # Issues Detection
        issues = []
        if tcp_analysis.get('errors'):
            issues.extend([f"TCP: {error}" for error in tcp_analysis['errors']])

        failed_methods = request_comparison.get('comparison', {}).get('failed_methods', [])
        if failed_methods:
            issues.append(f"Failed methods: {', '.join(failed_methods)}")

        if issues:
            logger.error("DETECTED ISSUES:")
            for issue in issues:
                logger.error(f"  - {issue}")
        else:
            logger.info("No major issues detected in network diagnostics")

        logger.info("=" * 80)