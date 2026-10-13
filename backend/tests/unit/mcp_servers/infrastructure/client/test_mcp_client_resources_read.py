"""resources/read is the delivery channel for MCP App view HTML: the decoded
text is bounded by mcp_app_resource_max_bytes, the wire response gets its own
pre-decode ceiling in the httpx hook, and the client refuses to read while
disconnected."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from mcp import types

from eneo.main.exceptions import MCPClientError
from eneo.mcp_servers.infrastructure.client import mcp_client as mcp_client_module
from eneo.mcp_servers.infrastructure.client.mcp_client import (
    MCP_RESOURCES_READ_RESPONSE_MAX_BYTES,
    MCPClient,
    _bound_mcp_response,
    _BoundedMCPResponseStream,
)


def _make_client() -> MCPClient:
    mock_server = MagicMock()
    mock_server.name = "test-server"
    mock_server.http_url = "http://localhost:8080"
    mock_server.http_auth_type = "none"
    return MCPClient(mock_server)


def _resource_result(
    *,
    text: str = "<html></html>",
    mime_type: str = "text/html;profile=mcp-app",
    meta: dict | None = None,
) -> types.ReadResourceResult:
    return types.ReadResourceResult(
        contents=[
            types.TextResourceContents.model_validate(
                {
                    "uri": "ui://weather/dashboard",
                    "text": text,
                    "mimeType": mime_type,
                    "_meta": meta,
                }
            )
        ]
    )


class TestReadResource:
    async def test_returns_first_content_block(self):
        client = _make_client()
        client.session = AsyncMock()
        ui_meta = {"io.modelcontextprotocol/ui": {"prefersBorder": True}}
        client.session.read_resource.return_value = _resource_result(meta=ui_meta)

        result = await client.read_resource("ui://weather/dashboard")

        assert result == {
            "uri": "ui://weather/dashboard",
            "text": "<html></html>",
            "mime_type": "text/html;profile=mcp-app",
            "meta": ui_meta,
        }

    async def test_oversized_text_raises(self, monkeypatch):
        client = _make_client()
        client.session = AsyncMock()
        client.session.read_resource.return_value = _resource_result(text="x" * 128)
        monkeypatch.setattr(
            mcp_client_module,
            "get_settings",
            lambda: SimpleNamespace(mcp_app_resource_max_bytes=64),
        )

        with pytest.raises(MCPClientError, match="exceeds the configured maximum"):
            await client.read_resource("ui://weather/dashboard")

    async def test_empty_contents_raises(self):
        client = _make_client()
        client.session = AsyncMock()
        client.session.read_resource.return_value = types.ReadResourceResult(
            contents=[]
        )

        with pytest.raises(MCPClientError, match="no contents"):
            await client.read_resource("ui://weather/dashboard")

    async def test_not_connected_raises(self):
        client = _make_client()

        with pytest.raises(MCPClientError, match="Not connected"):
            await client.read_resource("ui://weather/dashboard")


class TestWireCeilingDispatch:
    """The httpx response hook installs a bounded stream for resources/read;
    methods without a configured ceiling stay untouched."""

    @staticmethod
    def _response_for(method: str) -> httpx.Response:
        request = httpx.Request(
            "POST",
            "http://localhost:8080/mcp",
            content=json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": method, "params": {}}
            ).encode(),
        )

        class _Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"{}"

        return httpx.Response(200, request=request, stream=_Stream())

    async def test_resources_read_gets_bounded_stream(self):
        response = self._response_for("resources/read")

        await _bound_mcp_response(response, tools_max_bytes=1024, tools_max_count=16)

        assert isinstance(response.stream, _BoundedMCPResponseStream)
        assert response.stream._max_bytes == MCP_RESOURCES_READ_RESPONSE_MAX_BYTES

    async def test_unknown_method_stays_unbounded(self):
        response = self._response_for("resources/subscribe")
        original_stream = response.stream

        await _bound_mcp_response(response, tools_max_bytes=1024, tools_max_count=16)

        assert response.stream is original_stream
