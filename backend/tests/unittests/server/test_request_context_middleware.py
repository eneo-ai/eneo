"""Unit tests for RequestContextMiddleware audit-context capture."""

import asyncio
from uuid import UUID

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from eneo.main.config import get_settings
from eneo.main.request_context import (
    clear_request_context,
    get_request_context,
    set_request_context,
)
from eneo.server.middleware.request_context import RequestContextMiddleware


@pytest.fixture(autouse=True)
def reset_context():
    clear_request_context()
    yield
    clear_request_context()


def _build_app(captured: dict[str, dict]):
    """Build a tiny Starlette app whose /probe endpoint snapshots the context."""

    async def probe(request):  # noqa: ARG001
        captured["snapshot"] = get_request_context()
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/probe", probe)])
    app.add_middleware(RequestContextMiddleware)
    return app


def test_middleware_populates_user_agent_and_request_id():
    captured: dict[str, dict] = {}
    app = _build_app(captured)
    request_uuid = "550e8400-e29b-41d4-a716-446655440000"

    with TestClient(app) as client:
        response = client.get(
            "/probe",
            headers={
                "X-Request-Id": request_uuid,
                "User-Agent": "probe-agent/1.0",
            },
        )

    assert response.status_code == 200
    snap = captured["snapshot"]
    assert snap["user_agent"] == "probe-agent/1.0"
    assert snap["request_id"] == UUID(request_uuid)


def test_middleware_silently_drops_invalid_request_id():
    captured: dict[str, dict] = {}
    app = _build_app(captured)

    with TestClient(app) as client:
        response = client.get(
            "/probe",
            headers={"X-Request-Id": "not-a-uuid"},
        )

    assert response.status_code == 200
    snap = captured["snapshot"]
    assert "request_id" not in snap
    # set_request_context drops keys whose value is None, so the key is absent.


def test_middleware_falls_back_to_correlation_id_for_request_id():
    captured: dict[str, dict] = {}
    app = _build_app(captured)
    correlation_uuid = "11111111-1111-1111-1111-111111111111"

    with TestClient(app) as client:
        response = client.get(
            "/probe",
            headers={"X-Correlation-Id": correlation_uuid},
        )

    assert response.status_code == 200
    snap = captured["snapshot"]
    assert snap["request_id"] == UUID(correlation_uuid)


def test_middleware_resolves_client_ip_with_trusted_proxy(monkeypatch):
    captured: dict[str, dict] = {}
    app = _build_app(captured)

    settings = get_settings()
    monkeypatch.setattr(settings, "trusted_proxy_count", 1)
    monkeypatch.setattr(
        settings, "trusted_proxy_headers", ["x-forwarded-for", "x-real-ip"]
    )

    with TestClient(app) as client:
        # The proxy appends the client it accepted the connection from; an
        # earlier entry came with the request and is ignored.
        response = client.get(
            "/probe",
            headers={"X-Forwarded-For": "198.51.100.7, 203.0.113.45"},
        )

    assert response.status_code == 200
    snap = captured["snapshot"]
    assert snap["ip_address"] == "203.0.113.45"


def test_middleware_falls_back_to_client_host_without_proxy_config(monkeypatch):
    captured: dict[str, dict] = {}
    app = _build_app(captured)

    settings = get_settings()
    monkeypatch.setattr(settings, "trusted_proxy_count", 0)

    with TestClient(app) as client:
        response = client.get("/probe")

    assert response.status_code == 200
    snap = captured["snapshot"]
    # TestClient connects from the hostname "testclient", not a real IP.
    # resolve_client_ip rejects non-IP values so the audit INET column and
    # API-key allow-list parsing never see garbage. The fallback path is
    # still exercised — it just yields None rather than propagating the
    # hostname downstream.
    assert snap.get("ip_address") is None


def test_middleware_drops_non_ip_in_forwarded_for(monkeypatch):
    """A proxy injecting a non-IP value in X-Forwarded-For must not propagate
    downstream — extracted hop is validated before reaching audit logs."""
    captured: dict[str, dict] = {}
    app = _build_app(captured)

    settings = get_settings()
    monkeypatch.setattr(settings, "trusted_proxy_count", 1)
    monkeypatch.setattr(settings, "trusted_proxy_headers", ["x-forwarded-for"])

    with TestClient(app) as client:
        response = client.get(
            "/probe",
            headers={"X-Forwarded-For": "not-an-ip"},
        )

    assert response.status_code == 200
    snap = captured["snapshot"]
    assert snap.get("ip_address") is None


def test_middleware_clears_context_after_request():
    captured: dict[str, dict] = {}
    app = _build_app(captured)

    with TestClient(app) as client:
        client.get("/probe", headers={"User-Agent": "probe/1.0"})

    # Context must be cleared by the finally block on the parent task.
    assert get_request_context() == {}


def test_resolve_client_ip_invoked_with_settings(monkeypatch):
    """resolve_client_ip is called with the settings-configured proxy count."""
    captured_calls: list[tuple] = []

    def fake_resolve(request, *, trusted_proxy_count, trusted_proxy_headers):  # noqa: ARG001
        captured_calls.append((trusted_proxy_count, tuple(trusted_proxy_headers)))
        return "1.2.3.4"

    monkeypatch.setattr(
        "eneo.server.middleware.request_context.resolve_client_ip",
        fake_resolve,
    )

    settings = get_settings()
    monkeypatch.setattr(settings, "trusted_proxy_count", 3)
    monkeypatch.setattr(settings, "trusted_proxy_headers", ["x-forwarded-for"])

    captured: dict[str, dict] = {}
    app = _build_app(captured)
    with TestClient(app) as client:
        client.get("/probe")

    assert captured_calls == [(3, ("x-forwarded-for",))]
    assert captured["snapshot"]["ip_address"] == "1.2.3.4"


def test_middleware_calls_set_request_context(monkeypatch):
    """Sanity test that the middleware passes audit fields to set_request_context."""
    received: dict[str, dict] = {}

    def fake_set(**values):
        received.update(values)
        return values

    monkeypatch.setattr(
        "eneo.server.middleware.request_context.set_request_context", fake_set
    )

    captured: dict[str, dict] = {}
    app = _build_app(captured)
    with TestClient(app) as client:
        client.get(
            "/probe",
            headers={
                "X-Request-Id": "550e8400-e29b-41d4-a716-446655440000",
                "User-Agent": "agent/1.0",
            },
        )

    assert "ip_address" in received
    assert received["user_agent"] == "agent/1.0"
    assert received["request_id"] == UUID("550e8400-e29b-41d4-a716-446655440000")
    assert "correlation_id" in received  # existing field still set
    assert received["path"] == "/probe"
    assert received["method"] == "GET"


@pytest.mark.parametrize("trace_id", [None, "1234567890abcdef1234567890abcdef"])
def test_middleware_preserves_id_header_precedence(monkeypatch, trace_id):
    monkeypatch.setattr(
        "eneo.server.middleware.request_context._current_trace_id", lambda: trace_id
    )
    captured: dict[str, dict] = {}
    request_uuid = "550e8400-e29b-41d4-a716-446655440000"
    correlation_uuid = "11111111-1111-1111-1111-111111111111"
    with TestClient(_build_app(captured)) as client:
        client.get(
            "/probe",
            headers={
                "X-Request-ID": request_uuid,
                "X-Correlation-ID": correlation_uuid,
            },
        )
    context = captured["snapshot"]
    assert context.get("trace_id") == trace_id
    assert context["correlation_id"] == (trace_id or correlation_uuid)
    assert context["request_id"] == UUID(request_uuid)


def _scope(correlation_id="request-context-test"):
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/stream",
        "query_string": b"",
        "headers": [(b"x-correlation-id", correlation_id.encode())],
        "client": ("127.0.0.1", 1234),
        "server": ("localhost", 80),
    }


@pytest.mark.parametrize("outcome", ["complete", "error", "cancelled"])
async def test_context_spans_the_full_stream_and_clears_after_exit(
    monkeypatch, outcome
):
    monkeypatch.setattr(
        "eneo.server.middleware.request_context._current_trace_id", lambda: None
    )
    contexts = []
    final_context = None

    async def application(scope, receive, send):
        nonlocal final_context
        try:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await asyncio.sleep(0)
            await send(
                {"type": "http.response.body", "body": b"partial", "more_body": True}
            )
            if outcome == "error":
                raise RuntimeError("upstream failed")
            if outcome == "cancelled":
                raise asyncio.CancelledError
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            final_context = get_request_context()

    async def send(message):
        contexts.append(get_request_context())

    async def receive():
        await asyncio.Event().wait()

    middleware = RequestContextMiddleware(application)
    if outcome == "complete":
        await middleware(_scope(), receive, send)
    else:
        error = RuntimeError if outcome == "error" else asyncio.CancelledError
        with pytest.raises(error):
            await middleware(_scope(), receive, send)

    assert contexts
    assert all(
        context["correlation_id"] == "request-context-test" for context in contexts
    )
    assert final_context["correlation_id"] == "request-context-test"
    assert get_request_context() == {}


async def test_concurrent_request_contexts_are_isolated(monkeypatch):
    monkeypatch.setattr(
        "eneo.server.middleware.request_context._current_trace_id", lambda: None
    )
    both_started = asyncio.Event()
    contexts = []
    entered = 0

    async def application(scope, receive, send):
        nonlocal entered
        entered += 1
        if entered == 2:
            both_started.set()
        await both_started.wait()
        contexts.append(get_request_context())

    async def unused():
        raise AssertionError("unexpected receive/send")

    middleware = RequestContextMiddleware(application)
    async with asyncio.timeout(3):
        await asyncio.gather(
            middleware(_scope("first"), unused, unused),
            middleware(_scope("second"), unused, unused),
        )
    assert {context["correlation_id"] for context in contexts} == {"first", "second"}
    assert get_request_context() == {}


@pytest.mark.parametrize("scope_type", ["websocket", "lifespan"])
async def test_non_http_scopes_pass_through_unchanged(scope_type):
    scope = {"type": scope_type}
    received = []
    set_request_context(correlation_id="outer-context")

    async def application(inner_scope, inner_receive, inner_send):
        received.append((inner_scope, inner_receive, inner_send))
        assert get_request_context() == {"correlation_id": "outer-context"}

    async def unused():
        raise AssertionError("unexpected receive/send")

    await RequestContextMiddleware(application)(scope, unused, unused)
    assert received == [(scope, unused, unused)]
    assert received[0][0] is scope
    assert get_request_context() == {"correlation_id": "outer-context"}
