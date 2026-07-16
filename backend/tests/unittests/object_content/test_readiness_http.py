from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from eneo.object_content.runtime import (
    ObjectContentReadiness,
    ObjectContentReadinessCode,
    object_content_runtime,
)
from eneo.server.main import get_application
from eneo.worker import redis as worker_redis
from eneo.worker.redis.client import WorkerHealth


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
                    ready=False,
                    code=ObjectContentReadinessCode.STORE_UNAVAILABLE,
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
    unavailable = client.get("/api/readyz")
    recovered = client.get("/api/readyz")

    assert live.status_code == 200
    assert live.json() == {"detail": {"status": "HEALTHY"}}
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["object_content"] == {
        "status": "UNHEALTHY",
        "code": "store_unavailable",
    }
    assert recovered.status_code == 200
    assert recovered.json()["detail"]["object_content"] == {
        "status": "HEALTHY",
        "code": "ready",
    }


def test_readiness_is_healthy_and_explicit_when_object_content_is_disabled(
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
                code=ObjectContentReadinessCode.DISABLED,
            )
        ),
    )
    client = TestClient(get_application())

    response = client.get("/api/readyz")

    assert response.status_code == 200
    assert response.json()["detail"]["object_content"] == {
        "status": "DISABLED",
        "code": "disabled",
    }
