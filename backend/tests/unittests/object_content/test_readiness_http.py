import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection

import eneo.object_content.runtime as runtime_module
import eneo.server.main as server_main
from eneo.database.database import DatabaseSessionManager
from eneo.object_content.runtime import (
    ObjectContentReadiness,
    ObjectContentReadinessCode,
    ObjectContentRuntime,
    object_content_runtime,
)
from eneo.server.main import get_application
from eneo.worker import redis as worker_redis
from eneo.worker.redis.client import WorkerHealth


class _CountingDisabledDatabase(DatabaseSessionManager):
    def __init__(self, *, available: bool = True) -> None:
        super().__init__()
        self.available = available
        self.connect_count = 0
        self.connect_in_flight = 0
        self.peak_connect_in_flight = 0

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[AsyncConnection]:
        self.connect_count += 1
        self.connect_in_flight += 1
        self.peak_connect_in_flight = max(
            self.peak_connect_in_flight,
            self.connect_in_flight,
        )
        try:
            # Force overlap so this test proves the runtime lock is load-bearing.
            await asyncio.sleep(0)
            if not self.available:
                raise OSError("test PostgreSQL outage")
            connection = MagicMock(spec=AsyncConnection)
            result = MagicMock()
            result.scalar_one.return_value = False
            connection.execute = AsyncMock(return_value=result)
            yield cast(AsyncConnection, connection)
        finally:
            self.connect_in_flight -= 1


def test_liveness_stays_green_while_object_store_readiness_recovers(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        worker_redis,
        "get_worker_health",
        AsyncMock(return_value=WorkerHealth("HEALTHY", None, "ready")),
    )
    monkeypatch.setattr(
        object_content_runtime,
        "readiness",
        AsyncMock(
            side_effect=(
                ObjectContentReadiness(
                    ready=True,
                    code=ObjectContentReadinessCode.STORE_DEGRADED,
                ),
                ObjectContentReadiness(
                    ready=True,
                    code=ObjectContentReadinessCode.READY,
                ),
            )
        ),
    )
    client = TestClient(get_application())

    live = client.get("/api/livez")
    degraded = client.get("/api/readyz")
    recovered = client.get("/api/readyz")

    assert live.status_code == 200
    assert live.json() == {"detail": {"status": "HEALTHY"}}
    assert degraded.status_code == 200
    assert degraded.json()["detail"]["status"] == "DEGRADED"
    assert degraded.json()["detail"]["object_content"] == {
        "status": "DEGRADED",
        "code": "store_degraded",
    }
    assert recovered.status_code == 200
    assert recovered.json()["detail"]["object_content"] == {
        "status": "HEALTHY",
        "code": "ready",
    }


def test_readiness_is_healthy_when_object_store_is_not_configured(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        worker_redis,
        "get_worker_health",
        AsyncMock(return_value=WorkerHealth("HEALTHY", None, "ready")),
    )
    monkeypatch.setattr(
        object_content_runtime,
        "readiness",
        AsyncMock(
            return_value=ObjectContentReadiness(
                ready=True,
                code=ObjectContentReadinessCode.OBJECT_STORE_NOT_CONFIGURED,
            )
        ),
    )
    client = TestClient(get_application())

    response = client.get("/api/readyz")

    assert response.status_code == 200
    assert response.json()["detail"]["object_content"] == {
        "status": "NOT_CONFIGURED",
        "code": "object_store_not_configured",
    }


@pytest.mark.asyncio
async def test_concurrent_health_aliases_share_disabled_readiness_probe_and_expire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    monkeypatch.setattr(runtime_module, "monotonic", lambda: now)
    monkeypatch.setattr(runtime_module, "load_object_content_settings", lambda: None)
    monkeypatch.setattr(
        worker_redis,
        "get_worker_health",
        AsyncMock(return_value=WorkerHealth("HEALTHY", None, "ready")),
    )
    database = _CountingDisabledDatabase(available=False)
    runtime = ObjectContentRuntime(database=database)
    runtime.start()
    monkeypatch.setattr(server_main, "object_content_runtime", runtime)
    transport = ASGITransport(app=server_main.get_application())

    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test.local",
        ) as client:
            responses = await asyncio.gather(
                *(
                    client.get("/api/healthz" if index % 2 == 0 else "/api/readyz")
                    for index in range(16)
                )
            )

            assert {response.status_code for response in responses} == {503}
            assert database.connect_count == 1
            assert database.peak_connect_in_flight == 1

            database.available = True
            cached = await client.get("/api/readyz")

            assert cached.status_code == 503
            assert database.connect_count == 1

            now = 1.1
            refreshed = await client.get("/api/readyz")

            assert refreshed.status_code == 200
            assert database.connect_count == 2
    finally:
        await runtime.stop()
