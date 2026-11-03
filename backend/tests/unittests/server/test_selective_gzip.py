import asyncio
import gzip
import json

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from eneo.server.main import get_application
from eneo.server.middleware.compression import SelectiveGZipMiddleware

BIG = {"items": ["value"] * 400}  # well over the 500-byte minimum
GZIP = {"Accept-Encoding": "gzip"}


def _raw(content_type: str, **headers: str):
    async def endpoint(request):
        return Response(b"x" * 2000, media_type=content_type, headers=headers)

    return endpoint


async def _json(request):
    return JSONResponse(BIG)


async def _small(request):
    return JSONResponse({"ok": True})


async def _range(request):
    return Response(
        b"y" * 2000,
        status_code=206,
        media_type="application/json",
        headers={"Content-Range": "bytes 0-1999/4000"},
    )


def _client() -> TestClient:
    app = Starlette(
        routes=[
            Route("/json", _json),
            Route("/small", _small),
            Route(
                "/pdf",
                _raw(
                    "application/pdf",
                    **{"Content-Disposition": "attachment; filename=a.pdf"},
                ),
            ),
            Route(
                "/csv",
                _raw(
                    "text/csv", **{"Content-Disposition": "attachment; filename=a.csv"}
                ),
            ),
            Route(
                "/inline-json",
                _raw("application/json", **{"Content-Disposition": "inline"}),
            ),
            Route("/range", _range),
            Route("/encoded", _raw("application/json", **{"Content-Encoding": "br"})),
            Route("/octet", _raw("application/octet-stream")),
            Route("/ndjson", _raw("application/x-ndjson")),
            Route("/webm", _raw("audio/webm")),
        ]
    )
    return TestClient(SelectiveGZipMiddleware(app))


def _raw_get(client: TestClient, path: str, headers: dict[str, str] | None = None):
    # httpx decodes gzip transparently; keep the wire bytes to compare.
    with client.stream("GET", path, headers=headers or {}) as response:
        return response, b"".join(response.iter_raw())


def test_json_is_gzipped_with_vary():
    response, body = _raw_get(_client(), "/json", GZIP)

    assert response.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in response.headers["vary"]
    assert json.loads(gzip.decompress(body)) == BIG


def test_small_body_is_not_compressed():
    response, _ = _raw_get(_client(), "/small", GZIP)

    assert "content-encoding" not in response.headers


@pytest.mark.parametrize("path", ["/pdf", "/csv"])
def test_download_with_content_disposition_keeps_content_length(path: str):
    response, body = _raw_get(_client(), path, GZIP)

    assert "content-encoding" not in response.headers
    assert response.headers["content-length"] == "2000"
    assert body == b"x" * 2000


def test_inline_json_with_content_disposition_is_not_compressed():
    response, _ = _raw_get(_client(), "/inline-json", GZIP)

    assert "content-encoding" not in response.headers


async def test_event_stream_is_not_compressed_or_buffered():
    second_allowed = asyncio.Event()
    sent: list[dict] = []

    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"data: 1\n\n" * 100,
                "more_body": True,
            }
        )
        await second_allowed.wait()
        await send(
            {"type": "http.response.body", "body": b"data: 2\n\n", "more_body": False}
        )

    async def send(message):
        sent.append(message)
        if message.get("body", b"").startswith(b"data: 1"):
            second_allowed.set()

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "path": "/events",
        "method": "GET",
        "headers": [(b"accept-encoding", b"gzip")],
    }
    await asyncio.wait_for(
        SelectiveGZipMiddleware(app)(scope, receive, send), timeout=2
    )

    assert dict(sent[0]["headers"]).get(b"content-encoding") is None
    assert [m["body"][:7] for m in sent[1:]] == [b"data: 1", b"data: 2"]


def test_partial_content_206_untouched():
    response, body = _raw_get(_client(), "/range", GZIP)

    assert response.status_code == 206
    assert "content-encoding" not in response.headers
    assert response.headers["content-range"] == "bytes 0-1999/4000"
    assert body == b"y" * 2000


def test_already_encoded_response_untouched():
    response, body = _raw_get(_client(), "/encoded", GZIP)

    assert response.headers["content-encoding"] == "br"
    assert body == b"x" * 2000


@pytest.mark.parametrize("path", ["/octet", "/ndjson", "/webm"])
def test_unlisted_type_not_compressed(path: str):
    response, _ = _raw_get(_client(), path, GZIP)

    assert "content-encoding" not in response.headers
    assert response.headers["content-length"] == "2000"


@pytest.mark.parametrize(
    "accept_encoding", ["identity", "gzip;q=0, identity;q=1", "br", "*;q=0"]
)
def test_no_accept_encoding_passthrough(accept_encoding: str):
    response, body = _raw_get(_client(), "/json", {"Accept-Encoding": accept_encoding})

    assert "content-encoding" not in response.headers
    # The identity copy still varies by encoding, so caches keep them apart.
    assert "Accept-Encoding" in response.headers["vary"]
    assert json.loads(body) == BIG


@pytest.mark.parametrize("accept_encoding", ["gzip;q=0.5", "deflate, *"])
def test_gzip_accepted_with_quality_or_wildcard(accept_encoding: str):
    response, _ = _raw_get(_client(), "/json", {"Accept-Encoding": accept_encoding})

    assert response.headers["content-encoding"] == "gzip"


def test_excluded_identity_response_has_no_vary():
    response, _ = _raw_get(_client(), "/pdf", {"Accept-Encoding": "identity"})

    assert "vary" not in response.headers


async def test_repeated_accept_encoding_fields_honour_gzip_rejection():
    async def app(scope, receive, send):
        await JSONResponse(BIG)(scope, receive, send)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def run(headers: list[tuple[bytes, bytes]]) -> list[dict]:
        sent: list[dict] = []

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "path": "/", "method": "GET", "headers": headers}
        await SelectiveGZipMiddleware(app)(scope, receive, send)
        return sent

    repeated = await run(
        [(b"accept-encoding", b"*"), (b"accept-encoding", b"gzip;q=0, identity;q=1")]
    )
    combined = await run([(b"accept-encoding", b"*, gzip;q=0, identity;q=1")])

    for sent in (repeated, combined):
        assert b"content-encoding" not in dict(sent[0]["headers"])
        assert json.loads(b"".join(m.get("body", b"") for m in sent[1:])) == BIG


def test_production_app_compresses_openapi_json():
    response, body = _raw_get(TestClient(get_application()), "/openapi.json", GZIP)

    assert response.headers["content-encoding"] == "gzip"
    assert json.loads(gzip.decompress(body))["openapi"]
