"""
Container and system-level diagnostics for crawler failures
Focus on differences between urllib (works) and Scrapy/Twisted (fails) in container environment
"""
import asyncio
import os
from typing import Dict, Any

from intric.main.logging import get_logger

logger = get_logger(__name__)


class ContainerDiagnostics:
    """Diagnose container-specific issues that affect Twisted but not stdlib"""

    @staticmethod
    async def check_container_limits() -> Dict[str, Any]:
        """
        Check container resource limits that could affect Twisted
        Twisted is more sensitive to file descriptor and connection limits
        """
        logger.info("=== CONTAINER RESOURCE LIMITS ===")
        diagnostics = {}

        # 1. File descriptor limits (Twisted uses more FDs than urllib)
        try:
            import resource
            soft_limit, hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
            diagnostics['file_descriptors'] = {
                'soft_limit': soft_limit,
                'hard_limit': hard_limit
            }

            logger.info(f"File descriptor limits: soft={soft_limit}, hard={hard_limit}")

            if soft_limit < 1024:
                logger.error(f"🚫 LOW FILE DESCRIPTOR LIMIT: {soft_limit}")
                logger.error("   Twisted needs many file descriptors for connections")
                logger.error("   This could cause 'Too many open files' errors")
                logger.error("   Solution: Increase ulimit -n in container")

            # Count currently open FDs
            try:
                import subprocess
                result = subprocess.run(['ls', '/proc/self/fd'], capture_output=True, text=True)
                open_fds = len(result.stdout.split('\n')) - 1
                diagnostics['open_file_descriptors'] = open_fds
                logger.info(f"Currently open file descriptors: {open_fds}")

                if open_fds > soft_limit * 0.8:
                    logger.warning(f"⚠️  High FD usage: {open_fds}/{soft_limit}")
            except Exception as e:
                logger.debug(f"Could not count open FDs: {e}")

        except Exception as e:
            logger.warning(f"Could not check file descriptor limits: {e}")

        # 2. Memory limits
        try:
            with open('/sys/fs/cgroup/memory/memory.limit_in_bytes', 'r') as f:
                memory_limit = int(f.read().strip())
                diagnostics['memory_limit_bytes'] = memory_limit

                # Convert to readable format
                memory_limit_mb = memory_limit / (1024 * 1024)
                logger.info(f"Container memory limit: {memory_limit_mb:.0f} MB")

                if memory_limit_mb < 512:
                    logger.warning(f"⚠️  Low memory limit: {memory_limit_mb:.0f} MB")
        except Exception:
            logger.debug("Could not read cgroup memory limit")

        # 3. Network namespace isolation
        try:
            result = await asyncio.create_subprocess_exec(
                'ip', 'netns', 'identify',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            netns = stdout.decode().strip()

            if netns:
                logger.info(f"Running in network namespace: {netns}")
                diagnostics['network_namespace'] = netns
            else:
                logger.info("Running in default network namespace")

        except Exception:
            logger.debug("Could not check network namespace")

        logger.info("=" * 60)
        return diagnostics

    @staticmethod
    async def check_dns_resolution_methods(hostname: str) -> Dict[str, Any]:
        """
        Compare different DNS resolution methods
        Twisted might use different resolver than system
        """
        logger.info(f"=== DNS RESOLUTION COMPARISON for {hostname} ===")
        results = {'hostname': hostname, 'methods': {}}

        # 1. System getaddrinfo (what urllib uses)
        try:
            import socket
            addrs = socket.getaddrinfo(hostname, 80, socket.AF_UNSPEC, socket.SOCK_STREAM)
            ipv4_addrs = [addr[4][0] for addr in addrs if addr[0] == socket.AF_INET]
            ipv6_addrs = [addr[4][0] for addr in addrs if addr[0] == socket.AF_INET6]

            results['methods']['getaddrinfo'] = {
                'success': True,
                'ipv4': ipv4_addrs,
                'ipv6': ipv6_addrs
            }

            logger.info(f"✅ getaddrinfo (stdlib): IPv4={ipv4_addrs}, IPv6={ipv6_addrs}")

            # Check if IPv6 is tried first
            if ipv6_addrs and not ipv4_addrs:
                logger.warning("⚠️  Only IPv6 addresses found - IPv6 issues could cause timeouts")
            elif ipv6_addrs and ipv4_addrs:
                logger.info("Both IPv4 and IPv6 available")

        except Exception as e:
            results['methods']['getaddrinfo'] = {'success': False, 'error': str(e)}
            logger.error(f"❌ getaddrinfo failed: {e}")

        # 2. Twisted's DNS resolver
        try:

            logger.info("Testing Twisted DNS resolver...")
            # Note: This requires reactor running, will be captured in actual crawl

        except Exception as e:
            logger.debug(f"Could not test Twisted DNS: {e}")

        # 3. Check /etc/hosts for overrides
        try:
            with open('/etc/hosts', 'r') as f:
                hosts_content = f.read()
                if hostname in hosts_content:
                    logger.warning(f"⚠️  {hostname} found in /etc/hosts - may override DNS")
                    for line in hosts_content.split('\n'):
                        if hostname in line:
                            logger.info(f"   {line}")
        except Exception:
            pass

        # 4. Check if DNS is working at all
        try:
            result = await asyncio.create_subprocess_exec(
                'nslookup', hostname,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()

            if result.returncode == 0:
                logger.info("✅ nslookup successful")
            else:
                logger.error(f"❌ nslookup failed: {stderr.decode()}")

        except Exception as e:
            logger.debug(f"Could not run nslookup: {e}")

        logger.info("=" * 60)
        return results

    @staticmethod
    async def check_twisted_reactor_compatibility() -> Dict[str, Any]:
        """
        Check if Twisted reactor can actually start in this container environment
        """
        logger.info("=== TWISTED REACTOR COMPATIBILITY CHECK ===")
        diagnostics = {'reactor_type': None, 'can_import': False, 'potential_issues': []}

        # 1. Can we import Twisted?
        try:
            from twisted.internet import reactor
            diagnostics['can_import'] = True
            diagnostics['reactor_type'] = type(reactor).__name__

            logger.info("✅ Twisted imported successfully")
            logger.info(f"Reactor type: {type(reactor).__name__}")
            logger.info(f"Reactor module: {type(reactor).__module__}")

        except ImportError as e:
            logger.error(f"❌ Cannot import Twisted: {e}")
            diagnostics['error'] = str(e)
            return diagnostics

        # 2. Check Crochet (our async bridge)
        try:
            import crochet
            logger.info(f"✅ Crochet imported: {crochet.__version__ if hasattr(crochet, '__version__') else 'unknown version'}")

            # Check if crochet is already set up
            if hasattr(crochet, '_main'):
                logger.info("Crochet already initialized")
            else:
                logger.info("Crochet not yet initialized")

        except ImportError as e:
            logger.error(f"❌ Cannot import Crochet: {e}")
            diagnostics['potential_issues'].append("Crochet not available")

        # 3. Check thread support
        import threading
        logger.info(f"Threading available: {threading.active_count()} active threads")

        # List active threads
        for thread in threading.enumerate():
            logger.info(f"   Thread: {thread.name} (daemon={thread.daemon}, alive={thread.is_alive()})")

        # 4. Check event loop compatibility
        try:
            # Check if asyncio event loop is running
            try:
                asyncio.get_running_loop()
                logger.info("AsyncIO event loop is running")
                diagnostics['asyncio_running'] = True
            except RuntimeError:
                logger.info("No AsyncIO event loop running yet")
                diagnostics['asyncio_running'] = False

        except Exception as e:
            logger.debug(f"Could not check event loop: {e}")

        logger.info("=" * 60)
        return diagnostics

    @staticmethod
    async def check_connection_pooling_settings() -> Dict[str, Any]:
        """
        Check TCP connection settings that affect Scrapy but not urllib
        Scrapy maintains connection pools, urllib makes fresh connections
        """
        logger.info("=== CONNECTION POOLING & TCP SETTINGS ===")
        settings = {}

        # 1. TCP keepalive settings
        tcp_params = [
            'tcp_keepalive_time',
            'tcp_keepalive_intvl',
            'tcp_keepalive_probes',
            'tcp_fin_timeout',
            'tcp_tw_reuse',
            'tcp_tw_recycle'
        ]

        logger.info("TCP connection parameters:")
        for param in tcp_params:
            try:
                path = f'/proc/sys/net/ipv4/{param}'
                if os.path.exists(path):
                    with open(path, 'r') as f:
                        value = f.read().strip()
                        settings[param] = value
                        logger.info(f"   {param}: {value}")
            except Exception:
                pass

        # 2. Socket buffer sizes
        try:
            with open('/proc/sys/net/core/rmem_max', 'r') as f:
                rmem = f.read().strip()
            with open('/proc/sys/net/core/wmem_max', 'r') as f:
                wmem = f.read().strip()

            logger.info(f"Socket buffer sizes: rmem_max={rmem}, wmem_max={wmem}")
            settings['rmem_max'] = rmem
            settings['wmem_max'] = wmem

        except Exception:
            pass

        # 3. Connection tracking (important for connection reuse)
        try:
            with open('/proc/sys/net/netfilter/nf_conntrack_max', 'r') as f:
                conntrack_max = f.read().strip()
                logger.info(f"Connection tracking max: {conntrack_max}")
                settings['nf_conntrack_max'] = conntrack_max

        except Exception:
            logger.info("Connection tracking not available or not enabled")

        # 4. Check current connection count
        try:
            result = await asyncio.create_subprocess_exec(
                'ss', '-tan',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()

            if result.returncode == 0:
                lines = stdout.decode().split('\n')
                established = len([l for l in lines if 'ESTAB' in l])
                time_wait = len([l for l in lines if 'TIME-WAIT' in l])

                logger.info(f"Current connections: {established} established, {time_wait} time-wait")
                settings['current_connections'] = {'established': established, 'time_wait': time_wait}

                if time_wait > 100:
                    logger.warning(f"⚠️  High TIME-WAIT count: {time_wait}")
                    logger.warning("   Connection pooling may be exhausting available ports")

        except Exception:
            logger.debug("Could not check connection count")

        logger.info("=" * 60)
        return settings

    @staticmethod
    async def check_middleware_chain() -> Dict[str, Any]:
        """
        Verify that our custom middlewares aren't causing issues
        """
        logger.info("=== SCRAPY MIDDLEWARE VERIFICATION ===")

        try:
            from intric.crawler.crawler import create_runner
            import tempfile

            with tempfile.NamedTemporaryFile() as tmp:
                runner = create_runner(filepath=tmp.name)
                settings = runner.settings

                middlewares = settings.get('DOWNLOADER_MIDDLEWARES', {})
                enabled_middlewares = {k: v for k, v in middlewares.items() if v is not None}

                logger.info(f"Enabled middlewares ({len(enabled_middlewares)}):")
                for middleware, priority in sorted(enabled_middlewares.items(), key=lambda x: x[1]):
                    # Highlight our custom middlewares
                    if 'intric.crawler' in middleware:
                        logger.warning(f"   [CUSTOM] {middleware}: priority {priority}")
                    else:
                        logger.info(f"   {middleware}: priority {priority}")

                # Check if any middleware could be problematic
                if 'ForceHttp11Middleware' in str(middlewares):
                    logger.info("✅ ForceHttp11Middleware active - forcing HTTP/1.1")

                return {'middlewares': enabled_middlewares}

        except Exception as e:
            logger.error(f"Could not check middlewares: {e}")
            return {}

    @staticmethod
    async def run_all_container_diagnostics(url: str) -> Dict[str, Any]:
        """Run all container-specific diagnostics"""
        logger.info("=" * 80)
        logger.info("CONTAINER ENVIRONMENT DIAGNOSTICS")
        logger.info("=" * 80)

        from urllib.parse import urlparse
        parsed_url = urlparse(url)

        results = {}

        # Run all diagnostic checks
        results['limits'] = await ContainerDiagnostics.check_container_limits()
        results['dns'] = await ContainerDiagnostics.check_dns_resolution_methods(parsed_url.hostname)
        results['reactor'] = await ContainerDiagnostics.check_twisted_reactor_compatibility()
        results['tcp'] = await ContainerDiagnostics.check_connection_pooling_settings()
        results['middlewares'] = await ContainerDiagnostics.check_middleware_chain()

        logger.info("=" * 80)
        logger.info("CONTAINER DIAGNOSTICS COMPLETE")
        logger.info("=" * 80)

        return results