"""The MCP Apps extension is negotiated by attaching the
``io.modelcontextprotocol/ui`` entry to ``capabilities.extensions`` on the
outgoing InitializeRequest; every other request passes through untouched, and
the stock ClientSession is used while the feature flag is off."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from mcp import ClientSession, types

from eneo.mcp_servers.infrastructure.client import mcp_client as mcp_client_module
from eneo.mcp_servers.infrastructure.client.mcp_ui_session import (
    MCP_APP_MIME,
    MCP_APPS_EXTENSION_KEY,
    UiCapableClientSession,
)


def _initialize_request() -> types.ClientRequest:
    return types.ClientRequest(
        types.InitializeRequest(
            method="initialize",
            params=types.InitializeRequestParams(
                protocolVersion=types.LATEST_PROTOCOL_VERSION,
                capabilities=types.ClientCapabilities(),
                clientInfo=types.Implementation(name="eneo", version="test"),
            ),
        )
    )


async def test_initialize_request_carries_ui_extension_capability():
    session = object.__new__(UiCapableClientSession)
    request = _initialize_request()

    with patch(
        "mcp.shared.session.BaseSession.send_request", new_callable=AsyncMock
    ) as base_send:
        await UiCapableClientSession.send_request(
            session, request, types.InitializeResult
        )

    sent_request = base_send.call_args.args[0]
    wire = sent_request.model_dump(by_alias=True, exclude_none=True)
    assert wire["params"]["capabilities"]["extensions"] == {
        MCP_APPS_EXTENSION_KEY: {"mimeTypes": [MCP_APP_MIME]}
    }


async def test_non_initialize_requests_pass_through_unchanged():
    session = object.__new__(UiCapableClientSession)
    request = types.ClientRequest(types.PingRequest(method="ping"))

    with patch(
        "mcp.shared.session.BaseSession.send_request", new_callable=AsyncMock
    ) as base_send:
        await UiCapableClientSession.send_request(session, request, types.EmptyResult)

    sent_request = base_send.call_args.args[0]
    assert "extensions" not in sent_request.model_dump_json()


def test_session_class_follows_feature_flag(monkeypatch):
    monkeypatch.setattr(
        mcp_client_module,
        "get_settings",
        lambda: SimpleNamespace(mcp_apps_enabled=True),
    )
    assert mcp_client_module._session_class() is UiCapableClientSession

    monkeypatch.setattr(
        mcp_client_module,
        "get_settings",
        lambda: SimpleNamespace(mcp_apps_enabled=False),
    )
    assert mcp_client_module._session_class() is ClientSession
