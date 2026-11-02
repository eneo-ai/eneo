"""Audit routes keep the answers API clients read before the error envelope."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from eneo.audit.domain.export_job import ExportJob, ExportJobStatus
from eneo.audit.infrastructure.export_job_manager import ExportJobManager
from eneo.authentication.signed_urls import verify_audit_export_download_token
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


def test_export_status_keeps_the_authenticated_download_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tenant_id, job_id = uuid4(), uuid4()
    content = b"action,user\nlogin,fixture\n"
    path = tmp_path / "export.csv"
    path.write_bytes(content)
    job = ExportJob(
        job_id=job_id,
        tenant_id=tenant_id,
        status=ExportJobStatus.COMPLETED,
        progress=100,
        total_records=1,
        processed_records=1,
        file_path=str(path),
        file_size_bytes=len(content),
    )
    monkeypatch.setattr(ExportJobManager, "get_job", AsyncMock(return_value=job))
    admin = SimpleNamespace(id=uuid4(), tenant_id=tenant_id)
    client = _client(SimpleNamespace(user=lambda: admin, redis_client=lambda: None))
    base = f"/api/v1/audit/logs/export/{job_id}"

    body = client.get(f"{base}/status").json()

    # What develop answered: the credential-authenticated route, usable while
    # the export exists.
    assert body["download_url"] == f"{base}/download"
    signed = urlsplit(body["signed_download_url"])
    assert signed.path == f"{base}/signed-download"
    payload = verify_audit_export_download_token(parse_qs(signed.query)["token"][0])
    assert payload is not None
    assert payload["job_id"] == str(job_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["expires_at"] - payload["issued_at"] == 60
    assert client.get(body["signed_download_url"]).content == content
