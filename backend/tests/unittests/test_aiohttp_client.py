"""Unit tests for aiohttp client configuration (DNS caching and observability)."""

import pytest

from intric.main.aiohttp_client import AioHttpClient


@pytest.fixture
async def http_client():
    """Fixture providing configured AioHttpClient with proper cleanup."""
    client = AioHttpClient()
    client.start()
    yield client
    await client.stop()


@pytest.mark.asyncio
async def test_aiohttp_client_dns_caching(http_client):
    """Verify TCPConnector has DNS caching enabled."""
    assert http_client.session is not None, "Session should be initialized"
    assert http_client.session.connector is not None, "Connector should be present"

    # Verify DNS caching is enabled (public attribute)
    assert (
        http_client.session.connector.use_dns_cache is True
    ), "DNS caching should be enabled"


@pytest.mark.asyncio
async def test_aiohttp_client_has_trace_config():
    """Verify that TraceConfig is configured for DNS and connection timing."""
    client = AioHttpClient()
    client.start()

    try:
        assert client.session is not None
        assert client.session._trace_configs is not None
        assert len(client.session._trace_configs) > 0, "Should have at least one TraceConfig"

        # Verify trace config has the expected callbacks
        trace = client.session._trace_configs[0]
        assert trace._on_dns_resolvehost_start is not None, "Should have DNS start callback"
        assert trace._on_dns_resolvehost_end is not None, "Should have DNS end callback"
        assert (
            trace._on_connection_create_start is not None
        ), "Should have connection start callback"
        assert (
            trace._on_connection_create_end is not None
        ), "Should have connection end callback"

    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_aiohttp_client_singleton_starts_successfully():
    """Verify the singleton can be started and stopped without errors."""
    from intric.main.aiohttp_client import aiohttp_client

    # Start the singleton
    aiohttp_client.start()

    try:
        # Verify it's initialized
        assert aiohttp_client.session is not None
        assert aiohttp_client.session.connector is not None

        # Verify __call__ returns the session
        session = aiohttp_client()
        assert session is aiohttp_client.session

    finally:
        # Stop the singleton
        await aiohttp_client.stop()
