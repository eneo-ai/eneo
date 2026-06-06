"""Unit tests for per-server MCP identity-header forwarding (#5).

Covers the header builder's content/sanitization and that MCPClient forwards the
headers only when its own server opted in via ``forward_identity``.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from intric.mcp_servers.infrastructure.client.mcp_client import MCPClient
from intric.mcp_servers.infrastructure.identity_headers import build_identity_headers


def _user(**overrides):
    """A minimal user stand-in with the attributes the builder reads."""
    defaults = dict(
        id=uuid4(),
        email="anna.svensson@kommun.se",
        username="anna",
        tenant_id=uuid4(),
        roles=[SimpleNamespace(name="admin"), SimpleNamespace(name="editor")],
        tenant=SimpleNamespace(name="Kommun AB"),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestBuildIdentityHeaders:
    def test_returns_empty_when_no_user(self):
        assert build_identity_headers(None, None) == {}

    def test_emits_all_headers_when_populated(self):
        user = _user()
        headers = build_identity_headers(user, user.tenant)

        assert headers["X-Eneo-User-Id"] == str(user.id)
        assert headers["X-Eneo-User-Email"] == "anna.svensson@kommun.se"
        assert headers["X-Eneo-User-Name"] == "anna"
        assert headers["X-Eneo-Tenant-Id"] == str(user.tenant_id)
        assert headers["X-Eneo-Tenant-Name"] == "Kommun AB"
        assert headers["X-Eneo-Role"] == "admin, editor"

    def test_username_falls_back_to_email_local_part(self):
        headers = build_identity_headers(_user(username=None), None)
        assert headers["X-Eneo-User-Name"] == "anna.svensson"

    def test_strips_crlf_to_prevent_header_injection(self):
        user = _user(username="anna\r\nX-Injected: evil")
        headers = build_identity_headers(user, user.tenant)
        assert "\r" not in headers["X-Eneo-User-Name"]
        assert "\n" not in headers["X-Eneo-User-Name"]

    def test_non_latin1_value_is_encodable(self):
        # Emoji is not latin-1; the value must still encode as a request header.
        user = _user(username="anna \U0001f600")
        headers = build_identity_headers(user, user.tenant)
        headers["X-Eneo-User-Name"].encode("latin-1")  # must not raise

    def test_empty_values_are_omitted(self):
        user = _user(username=None, email=None, roles=[], tenant=None, tenant_id=None)
        headers = build_identity_headers(user, None)
        assert "X-Eneo-User-Email" not in headers
        assert "X-Eneo-Role" not in headers
        assert "X-Eneo-Tenant-Name" not in headers


class TestMCPClientIdentityForwarding:
    def _server(self, forward_identity: bool):
        server = MagicMock()
        server.name = "srv"
        server.http_url = "http://localhost:9000"
        server.http_auth_type = "bearer"
        server.forward_identity = forward_identity
        return server

    @pytest.mark.asyncio
    async def test_identity_forwarded_only_when_server_opted_in(self):
        identity = {"X-Eneo-User-Id": "u1", "X-Eneo-Tenant-Id": "t1"}

        opted_in = MCPClient(
            self._server(forward_identity=True),
            auth_credentials={"token": "secret"},
            identity_headers=identity,
        )
        headers = await opted_in._build_auth_headers()
        assert headers["Authorization"] == "Bearer secret"
        assert headers["X-Eneo-User-Id"] == "u1"
        assert headers["X-Eneo-Tenant-Id"] == "t1"

    @pytest.mark.asyncio
    async def test_identity_absent_when_not_opted_in(self):
        identity = {"X-Eneo-User-Id": "u1"}
        client = MCPClient(
            self._server(forward_identity=False),
            auth_credentials={"token": "secret"},
            identity_headers=identity,
        )
        headers = await client._build_auth_headers()
        assert headers == {"Authorization": "Bearer secret"}
        assert "X-Eneo-User-Id" not in headers
