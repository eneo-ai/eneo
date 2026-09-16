"""The What's new markers are personal, idempotent and session-only."""

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
async def test_seen_and_announced_are_tracked_independently(api_client, bearer_token):
    headers = {"Authorization": f"Bearer {bearer_token}"}

    initial = await api_client.get("/api/v1/whats-new/state/", headers=headers)
    assert initial.status_code == 200
    assert initial.json() == {"seen_version": None, "announced_version": None}

    # The announcement is shown before the page is ever opened.
    announced = await api_client.put(
        "/api/v1/whats-new/announced/", headers=headers, json={"version": "2.2.0"}
    )
    assert announced.status_code == 200
    assert announced.json() == {"seen_version": None, "announced_version": "2.2.0"}

    seen = await api_client.put(
        "/api/v1/whats-new/seen/", headers=headers, json={"version": "2.2.0"}
    )
    assert seen.json() == {"seen_version": "2.2.0", "announced_version": "2.2.0"}

    # A later release overwrites the single row instead of adding one.
    later = await api_client.put(
        "/api/v1/whats-new/seen/", headers=headers, json={"version": "2.3.0"}
    )
    assert later.json() == {"seen_version": "2.3.0", "announced_version": "2.2.0"}

    # An older frontend build cannot move a marker backwards.
    older = await api_client.put(
        "/api/v1/whats-new/seen/", headers=headers, json={"version": "2.2.0"}
    )
    assert older.json()["seen_version"] == "2.3.0"

    final = await api_client.get("/api/v1/whats-new/state/", headers=headers)
    assert final.json() == {"seen_version": "2.3.0", "announced_version": "2.2.0"}


@pytest.mark.integration
async def test_markers_reject_malformed_versions(api_client, bearer_token):
    headers = {"Authorization": f"Bearer {bearer_token}"}
    for path in ("/api/v1/whats-new/seen/", "/api/v1/whats-new/announced/"):
        response = await api_client.put(
            path, headers=headers, json={"version": "v2.2.0"}
        )
        assert response.status_code == 422


@pytest.mark.integration
async def test_markers_are_session_only(api_client, admin_user_api_key):
    headers = {"X-API-Key": admin_user_api_key.key}

    read = await api_client.get("/api/v1/whats-new/state/", headers=headers)
    assert read.status_code == 403

    for path in ("/api/v1/whats-new/seen/", "/api/v1/whats-new/announced/"):
        write = await api_client.put(path, headers=headers, json={"version": "2.2.0"})
        assert write.status_code == 403


@pytest.mark.integration
async def test_reset_forgets_both_markers_in_development(
    api_client, bearer_token, monkeypatch
):
    from eneo.main.config import get_settings

    headers = {"Authorization": f"Bearer {bearer_token}"}
    await api_client.put(
        "/api/v1/whats-new/announced/", headers=headers, json={"version": "2.2.0"}
    )
    await api_client.put(
        "/api/v1/whats-new/seen/", headers=headers, json={"version": "2.2.0"}
    )

    monkeypatch.setattr(get_settings(), "environment", "development")
    reset = await api_client.delete("/api/v1/whats-new/state/", headers=headers)
    assert reset.status_code == 200
    assert reset.json() == {"seen_version": None, "announced_version": None}

    state = await api_client.get("/api/v1/whats-new/state/", headers=headers)
    assert state.json() == {"seen_version": None, "announced_version": None}


@pytest.mark.integration
async def test_reset_is_hidden_outside_development(
    api_client, bearer_token, monkeypatch
):
    from eneo.main.config import get_settings

    monkeypatch.setattr(get_settings(), "environment", "production")
    response = await api_client.delete(
        "/api/v1/whats-new/state/", headers={"Authorization": f"Bearer {bearer_token}"}
    )
    assert response.status_code == 404
    assert "developer_tools_disabled" in response.text
