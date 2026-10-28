import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

from eneo.server.main import get_application
from eneo.server.middleware.api_response_headers import ApiResponseHeadersMiddleware

SANDBOX_CSP = "default-src 'none'; frame-ancestors 'none'; sandbox"
HSTS = "max-age=31536000"


async def _json(request):
    return JSONResponse({"ok": True})


async def _own_policy(request):
    return Response(
        b"icon",
        headers={
            "Cache-Control": "public, max-age=31536000",
            "Content-Security-Policy": "default-src 'self'",
            "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
        },
    )


async def _range(request):
    return Response(
        b"bcd",
        status_code=206,
        headers={
            "Content-Range": "bytes 1-3/10",
            "Accept-Ranges": "bytes",
            "Content-Type": "application/octet-stream",
        },
    )


async def _plain(request):
    return PlainTextResponse("plain")


async def _socket(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_text("hello")
    await websocket.close()


def _client(*, hsts: bool = False) -> TestClient:
    app = Starlette(
        routes=[
            Route("/api/v1/thing/", _json),
            Route("/api/v1/icon/", _own_policy),
            Route("/api/v1/file/", _range),
            Route("/version", _plain),
            Route("/openapi.json", _plain),
            Route("/docs", _plain),
            Route("/scim/v2/Users", _plain),
            WebSocketRoute("/api/v1/ws", _socket),
        ]
    )
    return TestClient(ApiResponseHeadersMiddleware(app, hsts=hsts))


def test_api_json_response_gets_default_headers():
    response = _client().get("/api/v1/thing/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == SANDBOX_CSP


def test_own_cache_control_and_csp_are_kept():
    response = _client(hsts=True).get("/api/v1/icon/")

    assert response.headers["cache-control"] == "public, max-age=31536000"
    assert response.headers.get_list("content-security-policy") == [
        "default-src 'self'"
    ]
    assert response.headers.get_list("strict-transport-security") == [
        "max-age=63072000; includeSubDomains"
    ]
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(("hsts", "expected"), [(True, HSTS), (False, None)])
def test_hsts_only_outside_development(hsts: bool, expected: str | None):
    response = _client(hsts=hsts).get("/api/v1/thing/")

    assert response.headers.get("strict-transport-security") == expected


@pytest.mark.parametrize(
    "path", ["/version", "/openapi.json", "/docs", "/scim/v2/Users"]
)
def test_non_api_paths_are_untouched(path: str):
    response = _client(hsts=True).get(path)

    assert response.status_code == 200
    for header in (
        "cache-control",
        "x-content-type-options",
        "content-security-policy",
        "strict-transport-security",
    ):
        assert header not in response.headers


def test_range_response_is_byte_identical():
    response = _client().get("/api/v1/file/")

    assert response.status_code == 206
    assert response.content == b"bcd"
    assert response.headers["content-range"] == "bytes 1-3/10"
    assert response.headers["content-length"] == "3"
    assert response.headers["accept-ranges"] == "bytes"


async def test_streaming_response_is_not_buffered():
    second_chunk_allowed = asyncio.Event()
    sent: list[dict] = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"one", "more_body": True})
        await second_chunk_allowed.wait()
        await send({"type": "http.response.body", "body": b"two", "more_body": False})

    async def send(message):
        sent.append(message)
        if message.get("body") == b"one":
            # The first chunk reached the server before the app produced the second.
            second_chunk_allowed.set()

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": "http", "path": "/api/v1/stream/", "method": "GET", "headers": []}
    await asyncio.wait_for(
        ApiResponseHeadersMiddleware(app, hsts=False)(scope, receive, send), timeout=2
    )

    assert [message.get("body") for message in sent[1:]] == [b"one", b"two"]
    headers = dict(sent[0]["headers"])
    assert headers[b"cache-control"] == b"no-store"


def test_websocket_scope_passes_through():
    with _client(hsts=True).websocket_connect("/api/v1/ws") as websocket:
        assert websocket.receive_text() == "hello"


def test_production_app_applies_headers(monkeypatch: pytest.MonkeyPatch):
    from eneo.main.config import get_settings

    monkeypatch.setattr(get_settings(), "environment", "production")
    response = TestClient(get_application()).get("/api/livez")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == SANDBOX_CSP
    assert response.headers["strict-transport-security"] == HSTS
