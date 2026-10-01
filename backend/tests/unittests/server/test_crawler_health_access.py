from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from eneo.main.config import Settings
from eneo.server.dependencies.container import Container
from eneo.server.main import get_application
from eneo.worker.redis import client as redis_module


@pytest.fixture(autouse=True)
def unavailable_database(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    session_scope = MagicMock(
        side_effect=RuntimeError("Database unavailable in unit test")
    )
    monkeypatch.setattr(Container, "session_scope", session_scope)
    return session_scope


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-API-Key": "invalid"},
        {"X-API-Key": "sk_tenant-admin-key"},
        {"Authorization": "Bearer tenant-admin-session"},
    ],
)
async def test_crawler_diagnostics_reject_non_sysadmin_before_reading_stores(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
    unavailable_database: MagicMock,
):
    monkeypatch.setattr(test_settings, "eneo_super_api_key", "deployment-admin-key")
    monkeypatch.setattr("eneo.authentication.auth.get_settings", lambda: test_settings)
    redis = AsyncMock()
    monkeypatch.setattr(redis_module, "get_redis", lambda: redis)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=get_application()), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/healthz/crawler?include_all=true", headers=headers
        )

    assert response.status_code == 401
    assert "debug" not in response.json()
    assert "pending" not in response.json()
    assert redis.mock_calls == []
    unavailable_database.assert_not_called()


@pytest.mark.parametrize("header_name", ["X-API-Key", "X-Deployment-Key"])
async def test_crawler_diagnostics_accept_super_key_using_configured_header(
    test_settings: Settings, monkeypatch: pytest.MonkeyPatch, header_name: str
):
    monkeypatch.setattr(test_settings, "eneo_super_api_key", "deployment-admin-key")
    monkeypatch.setattr(test_settings, "api_key_header_name", header_name)
    monkeypatch.setattr("eneo.authentication.auth.get_settings", lambda: test_settings)
    redis = AsyncMock()
    redis.ttl.return_value = 30
    redis.llen.return_value = 0
    redis.zcard.return_value = 0
    redis.get.return_value = b""
    redis.scan.return_value = (0, [])
    monkeypatch.setattr(redis_module, "get_redis", lambda: redis)

    # The diagnostics' existing degraded response works without a database;
    # this test needs no lifespan, server, Redis, or PostgreSQL process.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=get_application()), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/healthz/crawler?include_all=true",
            headers={header_name: "deployment-admin-key"},
        )
        liveness = await client.get("/api/livez")

    assert response.status_code == 200
    assert "debug" in response.json()
    assert liveness.status_code == 200


async def test_crawler_openapi_documents_sysadmin_authentication():
    operation = get_application().openapi()["paths"]["/api/healthz/crawler"]["get"]
    assert operation["security"]
    assert "401" in operation["responses"]
    assert operation["responses"]["401"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/GeneralError"
    }
