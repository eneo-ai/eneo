"""Integration tests to verify IPv4-only configuration in production HTTP clients.

These tests verify that all HTTP clients in the system are configured
to force IPv4 (AF_INET) and enable DNS caching.

For comprehensive OIDC flow testing with IPv4 enforcement, see:
- tests/integration/test_multi_tenant_federation_e2e.py
"""

import socket

import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_aiohttp_singleton_forces_ipv4_and_caches_dns():
    """
    Verify the global aiohttp_client singleton is configured with:
    - IPv4 forcing (family=socket.AF_INET)
    - DNS caching (use_dns_cache=True)

    This configuration prevents IPv6 blackhole timeouts and reduces
    DNS resolution delays for repeat requests.
    """
    from intric.main.aiohttp_client import aiohttp_client

    # Start the singleton (if not already started)
    aiohttp_client.start()

    try:
        # Verify session is initialized
        assert aiohttp_client.session is not None, "Singleton session should be initialized"
        assert (
            aiohttp_client.session.connector is not None
        ), "Singleton should have a connector"

        # Verify IPv4 forcing
        assert aiohttp_client.session.connector._family == socket.AF_INET, (
            f"Expected AF_INET ({socket.AF_INET}), "
            f"got {aiohttp_client.session.connector._family}. "
            "IPv4 forcing is not configured!"
        )

        # Verify DNS caching is enabled (public attribute)
        assert aiohttp_client.session.connector.use_dns_cache is True, (
            "DNS caching should be enabled to prevent repeated DNS lookups"
        )

        # Verify TraceConfig is present for observability
        assert (
            len(aiohttp_client.session._trace_configs) > 0
        ), "Should have TraceConfig for DNS/TCP timing observability"

    finally:
        # Stop the singleton (cleanup)
        await aiohttp_client.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_wrapped_aiohttp_client_also_forces_ipv4():
    """
    Verify that WrappedAiohttpClient (secondary HTTP client) also
    forces IPv4 for consistency across the system.
    """
    from intric.libs.clients.http_client import WrappedAiohttpClient

    client = WrappedAiohttpClient(base_url="http://test.example.com")

    try:
        assert client.client is not None
        assert client.client.connector is not None

        # Verify IPv4 forcing
        assert (
            client.client.connector._family == socket.AF_INET
        ), f"WrappedAiohttpClient should force IPv4, got family={client.client.connector._family}"

        # Verify DNS caching (public attribute)
        assert (
            client.client.connector.use_dns_cache is True
        ), "WrappedAiohttpClient should enable DNS caching"

    finally:
        await client.close()
