"""Audit routes keep the answers API clients read before the error envelope."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from eneo.main.exceptions import ErrorCodes
from eneo.server.endpoint_routes import endpoint_routes
from eneo.server.main import get_application


def _client(container: object) -> TestClient:
    """The production app, with the audit routes' container (and so the
    signed-in admin) replaced by `container`."""
    app = get_application()
    for route in endpoint_routes(app.routes):
        if route.path.startswith("/api/v1/audit/") and route.dependant:
            for dependency in route.dependant.dependencies:
                if dependency.name == "container":
                    app.dependency_overrides[dependency.call] = lambda: container
    return TestClient(app)


def test_audit_session_429_keeps_its_string_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = SimpleNamespace(eval=AsyncMock(return_value=[6, 1234]))
    monkeypatch.setattr("eneo.worker.redis.get_redis", lambda: redis)
    admin = SimpleNamespace(id=uuid4(), tenant_id=uuid4())

    response = _client(SimpleNamespace(user=lambda: admin)).post(
        "/api/v1/audit/access-session",
        json={"category": "incident", "description": "Reviewing a reported incident."},
        headers={"X-Request-ID": "req-audit-429"},
    )

    assert response.status_code == 429
    body = response.json()
    message = "Rate limit exceeded. Maximum 5 audit session creations per hour allowed."
    # A string on develop; the deprecated copy stays one for a release.
    assert body["detail"] == message
    assert body["code"] == "rate_limit_exceeded"
    assert body["message"] == message
    assert body["retry_after_seconds"] == 1234
    assert body["eneo_error_code"] == ErrorCodes.QUOTA_EXCEEDED.value
    assert body["request_id"] == "req-audit-429"
    assert response.headers["Retry-After"] == "1234"
