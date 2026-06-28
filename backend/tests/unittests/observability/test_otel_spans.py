"""Tests for OTEL span creation, X-Trace-Id propagation and span-attribute redaction.

Uses InMemorySpanExporter to verify spans without requiring an external trace backend.

Note: TestClient runs the ASGI app in a background thread so ContextVars do not
propagate from the test thread. Tests that check X-Trace-Id headers use
monkeypatching instead of relying on an active span in the test thread.

Severity convention: Python logging names (WARNING, CRITICAL) throughout.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from eneo.main.observability import (
    _aiohttp_request_hook,
    _httpx_request_hook,
    _server_request_hook,
    redact_url_query,
)
from eneo.main.request_context import clear_request_context
from eneo.server.middleware.request_context import RequestContextMiddleware
from eneo.server.middleware.trace_id import (
    TraceIdResponseMiddleware,
    current_trace_id,
)


@pytest.fixture()
def in_memory_tracer():
    """Isolated TracerProvider + InMemorySpanExporter for one test."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    original = trace.get_tracer_provider()
    trace.set_tracer_provider(provider)
    yield provider, exporter
    trace.set_tracer_provider(original)
    exporter.clear()


@pytest.fixture(autouse=True)
def _clear_ctx():
    clear_request_context()
    yield
    clear_request_context()


def _build_app():
    async def endpoint(request: Request):  # noqa: ARG001
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/ping", endpoint)])
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(TraceIdResponseMiddleware)
    return app


# ---------------------------------------------------------------------------
# _current_trace_id helper
# ---------------------------------------------------------------------------


def test_current_trace_id_returns_none_without_span():
    assert current_trace_id() is None


def test_current_trace_id_returns_32_hex_chars_with_active_span(in_memory_tracer):
    provider, _ = in_memory_tracer
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("root"):
        result = current_trace_id()

    assert result is not None
    assert len(result) == 32
    assert all(c in "0123456789abcdef" for c in result)


# ---------------------------------------------------------------------------
# X-Trace-Id header — via TraceIdResponseMiddleware (monkeypatched)
# ---------------------------------------------------------------------------

_FAKE_TRACE = "aabbccdd11223344aabbccdd11223344"


def test_x_trace_id_set_in_response(monkeypatch):
    monkeypatch.setattr(
        "eneo.server.middleware.trace_id.current_trace_id",
        lambda: _FAKE_TRACE,
    )
    app = _build_app()
    with TestClient(app) as client:
        response = client.get("/ping")

    assert response.status_code == 200
    assert response.headers.get("x-trace-id") == _FAKE_TRACE


def test_x_correlation_id_mirrors_trace_id(monkeypatch):
    monkeypatch.setattr(
        "eneo.server.middleware.trace_id.current_trace_id",
        lambda: _FAKE_TRACE,
    )
    app = _build_app()
    with TestClient(app) as client:
        response = client.get("/ping")

    assert response.headers.get("x-correlation-id") == _FAKE_TRACE


def test_no_trace_id_header_when_no_span():
    """Without an active span, X-Trace-Id is absent — no crash."""
    app = _build_app()
    with TestClient(app) as client:
        response = client.get("/ping")
    assert response.status_code == 200
    assert "x-trace-id" not in response.headers


# ---------------------------------------------------------------------------
# InMemorySpanExporter — span structure
# ---------------------------------------------------------------------------


def test_span_created_and_exported(in_memory_tracer):
    provider, exporter = in_memory_tracer
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("http-request"):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "http-request"


def test_span_has_valid_128bit_trace_id(in_memory_tracer):
    provider, exporter = in_memory_tracer
    with provider.get_tracer("t").start_as_current_span("root"):
        pass

    span = exporter.get_finished_spans()[0]
    ctx = span.get_span_context()
    assert ctx.is_valid
    assert ctx.trace_id != 0
    assert ctx.span_id != 0
    assert len(format(ctx.trace_id, "032x")) == 32
    assert len(format(ctx.span_id, "016x")) == 16


def test_child_spans_share_trace_id(in_memory_tracer):
    provider, exporter = in_memory_tracer
    tracer = provider.get_tracer("t")

    with tracer.start_as_current_span("root"):
        with tracer.start_as_current_span("child-db"):
            pass
        with tracer.start_as_current_span("child-redis"):
            pass

    trace_ids = {s.get_span_context().trace_id for s in exporter.get_finished_spans()}
    assert len(trace_ids) == 1, "All spans must share the same trace_id"


def test_parent_child_span_relationship(in_memory_tracer):
    provider, exporter = in_memory_tracer
    tracer = provider.get_tracer("t")

    with tracer.start_as_current_span("parent") as parent_span:
        parent_id = parent_span.get_span_context().span_id
        with tracer.start_as_current_span("child"):
            pass

    child = next(s for s in exporter.get_finished_spans() if s.name == "child")
    assert child.parent is not None
    assert child.parent.span_id == parent_id


# ---------------------------------------------------------------------------
# Span-attribute redaction — server (point 4)
# ---------------------------------------------------------------------------


def _recording_span(**attrs) -> MagicMock:
    """Return a mock span that records set_attribute calls."""
    span = MagicMock()
    span.is_recording.return_value = True
    span.attributes = dict(attrs)

    def _set(key, value):
        span.attributes[key] = value

    span.set_attribute.side_effect = _set
    return span


@pytest.mark.parametrize(
    "param,value",
    [
        ("code", "AUTH_CODE"),
        ("state", "CSRF"),
        ("token", "MY_TOKEN"),
        ("access_token", "ACCESS"),
        ("refresh_token", "REFRESH"),
        ("client_secret", "SECRET"),
        ("my_token_value", "SENSITIVE"),
    ],
)
def test_server_request_hook_redacts_url_query(param, value):
    """_server_request_hook must redact sensitive query params in url.query."""
    scope = {"query_string": f"{param}={value}&safe=ok".encode()}
    span = _recording_span()

    _server_request_hook(span, scope)

    url_query = span.attributes.get("url.query", "")
    assert value not in url_query
    assert f"{param}=[REDACTED]" in url_query
    assert "safe=ok" in url_query


def test_server_request_hook_redacts_existing_url_full():
    """If url.full is already set and contains sensitive params, it is redacted."""
    url = "https://api.example.com/cb?code=SECRET&page=1"
    span = _recording_span(**{"url.full": url})
    scope = {"query_string": b"code=SECRET&page=1"}

    _server_request_hook(span, scope)

    assert "SECRET" not in span.attributes.get("url.full", "")


def test_server_request_hook_redacts_auth_header_attribute():
    """Authorization header captured as span attribute must be redacted."""
    span = _recording_span(**{"http.request.header.authorization": "Bearer token123"})
    _server_request_hook(span, {})

    assert span.attributes.get("http.request.header.authorization") == "[REDACTED]"


def test_server_request_hook_noop_for_non_recording_span():
    """Hook must not crash on a non-recording span."""
    span = MagicMock()
    span.is_recording.return_value = False
    _server_request_hook(span, {})
    span.set_attribute.assert_not_called()


# ---------------------------------------------------------------------------
# Span-attribute redaction — httpx / aiohttp client hooks (point 4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "param,value",
    [
        ("code", "OAUTH_CODE"),
        ("client_secret", "TOP_SECRET"),
        ("access_token", "AT"),
        ("state", "CSRF_STATE"),
    ],
)
def test_httpx_request_hook_redacts_url_full(param, value):
    url = f"https://auth.example.com/token?{param}={value}&grant_type=code"
    span = _recording_span(**{"url.full": url})
    request_mock = MagicMock()

    _httpx_request_hook(span, request_mock)

    result = span.attributes.get("url.full", "")
    assert value not in result
    assert f"{param}=[REDACTED]" in result
    assert "grant_type=code" in result


@pytest.mark.parametrize("param,value", [("code", "CODE"), ("state", "ST")])
def test_aiohttp_request_hook_redacts_url_full(param, value):
    url = f"https://auth.example.com/cb?{param}={value}&safe=yes"
    span = _recording_span(**{"url.full": url})
    params_mock = MagicMock()

    _aiohttp_request_hook(span, params_mock)

    result = span.attributes.get("url.full", "")
    assert value not in result
    assert "safe=yes" in result


def test_httpx_hook_safe_url_unchanged():
    url = "https://api.example.com/data?page=1&limit=10"
    span = _recording_span(**{"url.full": url})
    _httpx_request_hook(span, MagicMock())
    assert span.attributes["url.full"] == url


# ---------------------------------------------------------------------------
# URL redaction helper (shared between log and span paths)
# ---------------------------------------------------------------------------


def test_redact_url_preserves_safe_params():
    url = "https://api.example.com/search?q=hello&page=2"
    assert redact_url_query(url) == url


def test_redact_url_hides_oauth_params():
    url = "https://auth.example.com/cb?code=AUTH_CODE&state=CSRF&session=ok"
    result = redact_url_query(url)
    assert "code=[REDACTED]" in result
    assert "state=[REDACTED]" in result
    assert "AUTH_CODE" not in result
    assert "CSRF" not in result
    assert "session=ok" in result
