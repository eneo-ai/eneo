"""The What's new read marker is personal, idempotent and session-only."""

from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def default_user(db_container):
    async with db_container() as container:
        return await container.user_repo().get_user_by_email("test@example.com")


@pytest.fixture
async def bearer_token(db_container, patch_auth_service_jwt, default_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(default_user)


@pytest.fixture
async def api_client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test.local",
    ) as client:
        yield client


@pytest.mark.integration
async def test_seen_marker_round_trip(api_client, bearer_token):
    headers = {"Authorization": f"Bearer {bearer_token}"}

    initial = await api_client.get("/api/v1/whats-new/seen/", headers=headers)
    assert initial.status_code == 200
    assert initial.json() == {"version": None, "seen_at": None}

    first = await api_client.put(
        "/api/v1/whats-new/seen/", headers=headers, json={"version": "2.2.0"}
    )
    assert first.status_code == 200
    assert first.json()["version"] == "2.2.0"
    first_seen_at = datetime.fromisoformat(first.json()["seen_at"])

    # A later release overwrites the single row instead of adding one.
    second = await api_client.put(
        "/api/v1/whats-new/seen/", headers=headers, json={"version": "2.3.0"}
    )
    assert second.status_code == 200
    assert second.json()["version"] == "2.3.0"
    assert datetime.fromisoformat(second.json()["seen_at"]) >= first_seen_at

    final = await api_client.get("/api/v1/whats-new/seen/", headers=headers)
    assert final.json()["version"] == "2.3.0"


@pytest.mark.integration
async def test_seen_marker_rejects_malformed_versions(api_client, bearer_token):
    response = await api_client.put(
        "/api/v1/whats-new/seen/",
        headers={"Authorization": f"Bearer {bearer_token}"},
        json={"version": "v2.2.0"},
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_seen_marker_is_session_only(api_client, admin_user_api_key):
    headers = {"X-API-Key": admin_user_api_key.key}

    read = await api_client.get("/api/v1/whats-new/seen/", headers=headers)
    assert read.status_code == 403

    write = await api_client.put(
        "/api/v1/whats-new/seen/", headers=headers, json={"version": "2.2.0"}
    )
    assert write.status_code == 403
