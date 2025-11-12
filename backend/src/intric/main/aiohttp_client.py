import time

import aiohttp

from intric.main.logging import get_logger

logger = get_logger(__name__)


class AioHttpClient:
    session: aiohttp.ClientSession = None

    def _create_trace_config(self) -> aiohttp.TraceConfig:
        """Create TraceConfig for DNS and connection timing observability."""
        trace = aiohttp.TraceConfig()

        async def on_dns_start(session, trace_config_ctx, params):
            trace_config_ctx._dns_start_time = time.perf_counter()

        async def on_dns_end(session, trace_config_ctx, params):
            if hasattr(trace_config_ctx, "_dns_start_time"):
                dns_duration_ms = (time.perf_counter() - trace_config_ctx._dns_start_time) * 1000

                # Warn if DNS resolution is slow (>2s indicates infrastructure issues)
                if dns_duration_ms > 2000:
                    logger.warning(
                        f"SLOW DNS resolution detected for {params.host}",
                        extra={
                            "event": "dns_slow",
                            "host": params.host,
                            "duration_ms": int(dns_duration_ms),
                            "threshold_ms": 2000,
                            "recommendation": "Check DNS server configuration (/etc/resolv.conf) for unreachable nameservers",
                        },
                    )
                else:
                    logger.debug(
                        f"DNS resolution completed for {params.host}",
                        extra={
                            "event": "dns_resolution",
                            "host": params.host,
                            "duration_ms": int(dns_duration_ms),
                        },
                    )

        async def on_conn_start(session, trace_config_ctx, params):
            trace_config_ctx._conn_start_time = time.perf_counter()

        async def on_conn_end(session, trace_config_ctx, params):
            if hasattr(trace_config_ctx, "_conn_start_time"):
                conn_duration_ms = (time.perf_counter() - trace_config_ctx._conn_start_time) * 1000

                # Safely get peername - params.transport may not exist in all aiohttp versions
                peername = None
                try:
                    if hasattr(params, 'transport') and params.transport:
                        peername = params.transport.get_extra_info("peername")
                except Exception:
                    # Don't let trace callback errors break the request
                    pass

                logger.debug(
                    f"TCP connection established to {peername or 'unknown'}",
                    extra={
                        "event": "tcp_connection",
                        "peername": str(peername) if peername else "unknown",
                        "duration_ms": int(conn_duration_ms),
                    },
                )

        # Register callbacks using .append() method (not decorator syntax)
        trace.on_dns_resolvehost_start.append(on_dns_start)
        trace.on_dns_resolvehost_end.append(on_dns_end)
        trace.on_connection_create_start.append(on_conn_start)
        trace.on_connection_create_end.append(on_conn_end)

        return trace

    def start(self):
        # Configure timeout (per-request timeouts can override these)
        timeout = aiohttp.ClientTimeout(
            total=30.0,  # Maximum time for entire request
            connect=10.0,  # Maximum time to establish connection
        )

        # Configure TCP connector for connection pooling and cleanup
        connector = aiohttp.TCPConnector(
            limit=100,  # Total connection pool size
            limit_per_host=30,  # Max connections per host
            enable_cleanup_closed=True,  # Clean up closed connections
            use_dns_cache=True,  # Cache DNS results to avoid repeated lookups
            ttl_dns_cache=300,  # Cache DNS for 5 minutes (conservative)
        )

        # Create trace config for observability
        trace_config = self._create_trace_config()

        self.session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            trace_configs=[trace_config],
        )

    async def stop(self):
        await self.session.close()
        self.session = None

    def __call__(self) -> aiohttp.ClientSession:
        assert self.session is not None
        return self.session


aiohttp_client = AioHttpClient()
