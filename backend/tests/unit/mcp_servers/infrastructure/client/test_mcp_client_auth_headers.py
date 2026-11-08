"""Auth header construction for MCPClient (bearer, api_key_header, bundled)."""

from uuid import uuid4

from eneo.main.config import get_settings
from eneo.mcp_servers.domain.entities.mcp_server import (
    MCPServer,
    MCPServerBackingModel,
)
from eneo.mcp_servers.infrastructure.client import mcp_client as client_module
from eneo.mcp_servers.infrastructure.client.mcp_client import MCPClient


def _make_server() -> MCPServer:
    return MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Provider",
        http_url="https://provider.example/mcp",
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
                "tool_runtime_url": "http://tool-runtime:8080",
                "tool_runtime_token": "runtime-secret",
                "file_reference_base_url": "http://backend:8000/",
                "mcp_apps_enabled": False,
            }
        )
        monkeypatch.setattr(client_module, "get_settings", lambda: settings)
        server = _make_server()
        server.http_url = "http://tool-runtime:8080/mcp/compute"
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

    async def test_bundled_server_is_told_when_tool_views_are_shown(self, monkeypatch):
        base = {
            "tool_runtime_url": "http://tool-runtime:8080",
            "tool_runtime_token": "runtime-secret",
            "mcp_apps_enabled": True,
        }
        server = _make_server()
        server.http_url = "http://tool-runtime:8080/mcp/file-analysis"
        server.http_auth_type = "bundled"

        async def headers_with(**settings):
            configured = get_settings().model_copy(update={**base, **settings})
            monkeypatch.setattr(client_module, "get_settings", lambda: configured)
            return await MCPClient(server, None)._build_auth_headers()

        shown = await headers_with(mcp_app_content_base_url="http://content.test")
        assert shown["X-Eneo-Tool-Views"] == "shown"
        # Views enabled but with nowhere to serve them from are not shown.
        unserved = await headers_with(mcp_app_content_base_url=None)
        assert "X-Eneo-Tool-Views" not in unserved


async def test_existing_bundled_registration_forwards_only_opaque_identity(monkeypatch):
    settings = get_settings().model_copy(
        update={
            "tool_runtime_url": "http://tool-runtime:3010",
            "tool_runtime_token": "runtime-secret",
            "file_reference_base_url": "http://backend:8000",
            "mcp_apps_enabled": False,
        }
    )
    monkeypatch.setattr(client_module, "get_settings", lambda: settings)
    server = _make_server()
    server.http_auth_type = "bundled"
    server.forward_identity = False
    server.http_url = "http://tool-runtime:3010/mcp/compute"
    identity = {
        "X-Eneo-Tenant-Id": str(uuid4()),
        "X-Eneo-User-Id": str(uuid4()),
        "X-Eneo-User-Email": "private@example.com",
    }
    headers = await MCPClient(
        server, None, identity_headers=identity
    )._build_auth_headers()
    assert headers["X-Eneo-User-Id"] == identity["X-Eneo-User-Id"]
    assert headers["X-Eneo-Tenant-Id"] == identity["X-Eneo-Tenant-Id"]
    assert "X-Eneo-User-Email" not in headers
    server.http_auth_type = "bearer"
    server.http_url = "https://provider.example/mcp"
    headers = await MCPClient(
        server, None, identity_headers=identity
    )._build_auth_headers()
    assert not any(key.lower().startswith("x-eneo-") for key in headers)


async def test_a_forecast_source_names_the_model_eneo_selected(monkeypatch):
    settings = get_settings().model_copy(
        update={
            "tool_runtime_url": "http://tool-runtime:3010",
            "tool_runtime_token": "runtime-secret",
            "mcp_apps_enabled": False,
        }
    )
    monkeypatch.setattr(client_module, "get_settings", lambda: settings)

    def source(model_key: str | None) -> MCPServer:
        return MCPServer(
            id=uuid4(),
            tenant_id=uuid4(),
            name="Forecast",
            http_url="http://tool-runtime:3010/mcp/forecast",
            http_auth_type="bundled",
            purpose="forecast",
            forecast_model=(
                MCPServerBackingModel(
                    id=uuid4(),
                    name=model_key,
                    nickname="Timestral",
                    provider_name="Eneo tool service",
                    is_enabled=True,
                    is_deleted=False,
                    security_classification=None,
                )
                if model_key is not None
                else None
            ),
        )

    cpu = await MCPClient(source("default"), None)._build_auth_headers()
    gpu = await MCPClient(source("gpu-large"), None)._build_auth_headers()
    none = await MCPClient(source(None), None)._build_auth_headers()

    assert cpu["X-Eneo-Model"] == "default"
    assert gpu["X-Eneo-Model"] == "gpu-large"
    assert "X-Eneo-Model" not in none
