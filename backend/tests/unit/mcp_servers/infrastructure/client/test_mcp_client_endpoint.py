"""Which URL MCPClient connects to.

An external server is reached at the URL an administrator stored. A built-in
provider runs on Eneo's own loopback, so it is reached at the loopback address
configured now, whatever URL its row still carries from when it was saved.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
from eneo.mcp_servers.infrastructure.client import mcp_client
from eneo.mcp_servers.infrastructure.client.mcp_client import (
    MCPClient,
    endpoint_url,
    loopback_endpoint,
)

STALE_URL = "http://localhost:8123/internal-mcp/image_generation/mcp"


@pytest.fixture(autouse=True)
def configured_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mcp_client,
        "get_settings",
        lambda: SimpleNamespace(internal_mcp_base_url="http://eneo-backend:9000/"),
    )


def _builtin_provider(http_url: str = STALE_URL) -> MCPServer:
    return MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Images",
        http_url=http_url,
        http_auth_type="internal",
        purpose="image_generation",
    )


def _external_server(**overrides: str) -> MCPServer:
    return MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Provider",
        http_url="https://provider.example/mcp",
        **overrides,
    )


def test_loopback_endpoint_is_mounted_under_the_server_name():
    assert (
        loopback_endpoint("knowledge")
        == "http://eneo-backend:9000/internal-mcp/knowledge/mcp"
    )


def test_builtin_provider_follows_the_configured_loopback_not_its_stored_url():
    assert (
        endpoint_url(_builtin_provider())
        == "http://eneo-backend:9000/internal-mcp/image_generation/mcp"
    )


def test_builtin_provider_never_connects_to_a_foreign_stored_url():
    server = _builtin_provider(http_url="https://attacker.example/mcp")

    assert MCPClient(server).endpoint_url.startswith("http://eneo-backend:9000/")


def test_external_server_keeps_its_stored_url():
    assert endpoint_url(_external_server()) == "https://provider.example/mcp"


def test_external_capability_provider_keeps_its_stored_url():
    server = _external_server(purpose="image_generation", http_auth_type="bearer")

    assert endpoint_url(server) == "https://provider.example/mcp"


async def test_connect_opens_the_transport_at_the_resolved_endpoint(
    monkeypatch: pytest.MonkeyPatch,
):
    opened: list[str] = []

    @asynccontextmanager
    async def fake_transport(url: str, **_: object):
        opened.append(url)
        raise ConnectionError("stop after recording the url")
        yield  # pragma: no cover

    monkeypatch.setattr(mcp_client, "_open_streamable_http_client", fake_transport)

    with pytest.raises(ConnectionError):
        await MCPClient(_builtin_provider())._connect_internal()

    assert opened == ["http://eneo-backend:9000/internal-mcp/image_generation/mcp"]
