"""Auth header construction for MCPClient (bearer, api_key_header, bundled)."""

from uuid import uuid4

from eneo.main.config import get_settings
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
from eneo.mcp_servers.infrastructure.client import mcp_client as client_module
from eneo.mcp_servers.infrastructure.client.mcp_client import MCPClient


def _make_server() -> MCPServer:
    return MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Provider",
        http_url="http://provider.example/mcp",
    )


class TestAuthHeaderConstruction:
    async def test_api_key_header(self):
        server = _make_server()
        server.http_auth_type = "api_key_header"
        client = MCPClient(server, {"header_name": "X-Api-Key", "token": "sk-secret"})

        headers = await client._build_auth_headers()

        assert headers == {"X-Api-Key": "sk-secret"}

    async def test_bearer_header(self):
        server = _make_server()
        server.http_auth_type = "bearer"
        client = MCPClient(server, {"token": "sk-secret"})

        headers = await client._build_auth_headers()

        assert headers == {"Authorization": "Bearer sk-secret"}

    async def test_api_key_header_without_credentials_sends_nothing(self):
        server = _make_server()
        server.http_auth_type = "api_key_header"
        client = MCPClient(server, None)

        headers = await client._build_auth_headers()

        assert headers == {}

    async def test_bundled_server_uses_the_deployment_token_and_file_origin(
        self, monkeypatch
    ):
        settings = get_settings().model_copy(
            update={
                "tool_runtime_token": "runtime-secret",
                "file_reference_base_url": "http://backend:8000/",
            }
        )
        monkeypatch.setattr(client_module, "get_settings", lambda: settings)
        server = _make_server()
        server.http_auth_type = "bundled"
        # Stored credentials are ignored: the row never carries one.
        client = MCPClient(server, {"token": "stored"})

        headers = await client._build_auth_headers()

        assert headers == {
            "Authorization": "Bearer runtime-secret",
            "X-Eneo-File-Origin": "http://backend:8000",
        }

    async def test_external_servers_never_get_the_file_origin(self):
        server = _make_server()
        server.http_auth_type = "bearer"
        client = MCPClient(server, {"token": "sk-secret"})

        headers = await client._build_auth_headers()

        assert "X-Eneo-File-Origin" not in headers
