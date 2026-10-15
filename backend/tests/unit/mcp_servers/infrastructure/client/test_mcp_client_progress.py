"""A progress callback on a tool call is handed to the MCP session, which
puts a progress token on the request; without one, none is requested."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
from eneo.mcp_servers.infrastructure.client.mcp_client import MCPClient


class _Session:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def call_tool(self, name, arguments=None, progress_callback=None):
        self.calls.append(
            {"name": name, "arguments": arguments, "progress": progress_callback}
        )
        if progress_callback is not None:
            await progress_callback(1, 2, "half")
        return SimpleNamespace(content=[], isError=False)


def _client() -> tuple[MCPClient, _Session]:
    server = MCPServer(
        id=uuid4(), tenant_id=uuid4(), name="p", http_url="http://p.example/mcp"
    )
    client = MCPClient(server, None)
    session = _Session()
    client.session = session  # type: ignore[assignment]
    return client, session


async def test_progress_callback_reaches_the_session_and_is_called():
    client, session = _client()
    heard: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress, total, message):
        heard.append((progress, total, message))

    result = await client.call_tool("tool", {"q": 1}, progress_callback=on_progress)

    assert result["is_error"] is False
    assert session.calls[0]["progress"] is on_progress
    assert heard == [(1, 2, "half")]


async def test_without_a_callback_no_progress_is_requested():
    client, session = _client()

    await client.call_tool("tool", {})

    assert session.calls[0]["progress"] is None
