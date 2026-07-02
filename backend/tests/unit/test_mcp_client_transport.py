"""Transport wiring for the HTTP MCP client.

`streamable_http_client` does not close a caller-provided httpx client, so the
MCP client owns that client: it must configure bearer auth and the SSE read
timeout on it, and close it on disconnect so connections are not leaked.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eneo.mcp_servers.infrastructure.client.mcp_client import MCPClient

_MODULE = "eneo.mcp_servers.infrastructure.client.mcp_client"


def _bearer_server() -> MagicMock:
    server = MagicMock()
    server.http_url = "http://localhost:8080/mcp"
    server.http_auth_type = "bearer"
    server.name = "test-server"
    return server


def _fake_transport() -> MagicMock:
    streams = MagicMock()
    streams.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
    streams.__aexit__ = AsyncMock(return_value=None)
    return streams


def _fake_session_ctx() -> MagicMock:
    session = MagicMock()
    session.initialize = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


@pytest.mark.asyncio
async def test_connect_configures_auth_and_sse_timeout_on_owned_client():
    client = MCPClient(
        _bearer_server(),
        auth_credentials={"token": "secret-token"},
        timeout=42,
    )
    http_client = MagicMock()
    http_client.aclose = AsyncMock()

    with (
        patch(f"{_MODULE}.httpx.AsyncClient", return_value=http_client) as async_client,
        patch(
            f"{_MODULE}.streamable_http_client", return_value=_fake_transport()
        ) as transport,
        patch(f"{_MODULE}.ClientSession", return_value=_fake_session_ctx()),
    ):
        await client.connect()

    kwargs = async_client.call_args.kwargs
    assert kwargs["headers"] == {"Authorization": "Bearer secret-token"}
    assert kwargs["follow_redirects"] is True
    # Base timeout is the connect budget; read stays at the SDK's 300s SSE default.
    assert kwargs["timeout"].connect == 42
    assert kwargs["timeout"].read == 300

    # The transport receives the owned client, not raw headers/timeout.
    assert transport.call_args.kwargs["http_client"] is http_client


@pytest.mark.asyncio
async def test_disconnect_closes_owned_client():
    client = MCPClient(_bearer_server(), auth_credentials={"token": "t"})
    http_client = MagicMock()
    http_client.aclose = AsyncMock()

    with (
        patch(f"{_MODULE}.httpx.AsyncClient", return_value=http_client),
        patch(f"{_MODULE}.streamable_http_client", return_value=_fake_transport()),
        patch(f"{_MODULE}.ClientSession", return_value=_fake_session_ctx()),
    ):
        await client.connect()
        await client.disconnect()

    http_client.aclose.assert_awaited_once()
