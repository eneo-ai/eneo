"""Unit tests for RequestContextMiddleware audit-context capture."""

from uuid import UUID

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from intric.main.config import get_settings
from intric.main.request_context import (
    clear_request_context,
    get_request_context,
)
from intric.server.middleware.request_context import RequestContextMiddleware


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
        response = client.get(
            "/probe",
            headers={"X-Forwarded-For": "203.0.113.45, 10.0.0.1"},
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
    # TestClient connects from a fixed test host (typically "testclient")
    assert snap["ip_address"] is not None


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
        "intric.server.middleware.request_context.resolve_client_ip",
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


def test_dispatch_calls_set_request_context(monkeypatch):
    """Sanity test that the middleware passes audit fields to set_request_context."""
    received: dict[str, dict] = {}

    def fake_set(**values):
        received.update(values)
        return values

    monkeypatch.setattr(
        "intric.server.middleware.request_context.set_request_context", fake_set
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
