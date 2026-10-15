"""A tool sync reads each declared MCP App view over the real transport. A
server that answers a read with an HTTP error fails the connection: no further
view is read, none is stored, and the tools still sync. A sync whose caller
times out stops and stores nothing."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI, Response

from eneo.mcp_servers.application.mcp_server_service import MCPServerService
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
from tests.unit.mcp_test_server import (
    Answer,
    one_tool_app,
    serve_test_app,
    unanswered,
)

VIEW_URI = "ui://lookup/view"
SECOND_VIEW_URI = "ui://forecast/view"
SYNCED = SimpleNamespace(
    new_tools=[], changed_tools=[], removed_tools=[], unchanged_count=0
)


class _Repo:
    def __init__(self) -> None:
        self.upserts: list[dict[str, object]] = []

    async def upsert(self, **kwargs: object) -> None:
        self.upserts.append(kwargs)


def _service(repo: _Repo) -> MCPServerService:
    user = SimpleNamespace(
        id=uuid4(),
        email="anna.svensson@kommun.se",
        username="anna",
        tenant_id=uuid4(),
        roles=[],
        tenant=None,
    )
    service = MCPServerService(
        mcp_server_repo=MagicMock(),
        mcp_server_tool_repo=MagicMock(),
        user=user,  # type: ignore[arg-type]
        app_view_repo=repo,  # type: ignore[arg-type]
    )
    service._sync_discovered_tool_definitions = AsyncMock(  # type: ignore[method-assign]
        return_value=SYNCED
    )
    return service


def _app(read_response: Callable[[FastAPI], Callable[[object], Answer]]) -> FastAPI:
    app = one_tool_app(
        lambda _: Response(status_code=500),
        tool_meta={"ui": {"resourceUri": VIEW_URI}},
        read_response=lambda request_id: answer(request_id),
        extra_tools=[
            {
                "name": "forecast",
                "inputSchema": {"type": "object"},
                "_meta": {"ui": {"resourceUri": SECOND_VIEW_URI}},
            }
        ],
    )
    answer = read_response(app)
    return app


@asynccontextmanager
async def _views_enabled(app: FastAPI) -> AsyncIterator[MCPServer]:
    settings = SimpleNamespace(
        mcp_apps_enabled=True, mcp_app_resource_max_bytes=1024 * 1024
    )
    with patch(
        "eneo.mcp_servers.application.mcp_server_service.get_settings",
        return_value=settings,
    ):
        async with serve_test_app(app) as url:
            yield MCPServer(tenant_id=uuid4(), name="views", http_url=url)


@pytest.mark.asyncio
async def test_an_http_error_on_a_view_read_leaves_the_view_out_and_syncs():
    # Kills the mutants that re-raise every cancellation of a read, and that
    # read the second view on the failed connection: either aborts the sync.
    repo = _Repo()
    service = _service(repo)
    app = _app(lambda _: lambda _: Response(status_code=500))
    async with _views_enabled(app) as server:
        result = await service.discover_and_sync_tools(server)

    assert result is SYNCED
    tool_defs = service._sync_discovered_tool_definitions.await_args.args[1]
    assert [tool["name"] for tool in tool_defs] == ["lookup", "forecast"]
    assert all("ui_resource_sha256" not in tool for tool in tool_defs)
    assert repo.upserts == []
    assert app.state.requests.count("resources/read") == 1


@pytest.mark.asyncio
async def test_a_sync_whose_caller_times_out_stops_and_stores_nothing():
    # Kills the mutant that turns the caller's cancellation into a failed
    # read: the sync would go on and the caller's timeout would not fire.
    repo = _Repo()
    service = _service(repo)
    async with _views_enabled(_app(lambda app: lambda _: unanswered(app))) as server:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.5):
                await service.discover_and_sync_tools(server)

    service._sync_discovered_tool_definitions.assert_not_awaited()
    assert repo.upserts == []
