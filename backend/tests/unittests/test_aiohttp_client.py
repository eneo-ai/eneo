"""Unit tests for aiohttp client configuration (IPv4 forcing and DNS caching)."""

import socket

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
async def test_aiohttp_client_forces_ipv4(http_client):
    """Verify TCPConnector is configured with AF_INET to force IPv4-only connections."""
    assert http_client.session is not None, "Session should be initialized"
    assert http_client.session.connector is not None, "Connector should be present"

    # Verify IPv4 forcing
    assert (
        http_client.session.connector._family == socket.AF_INET
    ), f"Expected AF_INET ({socket.AF_INET}), got {http_client.session.connector._family}"

    # Verify DNS caching is enabled (public attribute)
    assert (
        http_client.session.connector.use_dns_cache is True
    ), "DNS caching should be enabled"


@pytest.mark.asyncio
async def test_connector_configured_for_ipv4_dns(http_client):
    """
    Verify connector is configured to use AF_INET for IPv4-only DNS resolution.

    This is a simple configuration check. Integration tests verify the actual
    runtime behavior with real network interactions.
    """
    # Verify IPv4-only configuration
    assert http_client.session.connector._family == socket.AF_INET, (
        f"Connector should be configured with AF_INET ({socket.AF_INET}), "
        f"got {http_client.session.connector._family}"
    )


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
