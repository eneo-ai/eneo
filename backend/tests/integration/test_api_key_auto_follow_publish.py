"""Integration tests for auto-follow API key subscriptions on publish actions."""

from __future__ import annotations

from uuid import uuid4

import pytest


@pytest.fixture
async def default_user(db_container):
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.get_user_by_email("test@example.com")
    return user


@pytest.fixture
async def default_user_token(db_container, patch_auth_service_jwt, default_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(default_user)
    return token


async def _create_space_id(client, bearer_token: str) -> str:
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"auto-follow-space-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_assistant_id(client, bearer_token: str, space_id: str) -> str:
    response = await client.post(
        "/api/v1/assistants/",
        json={
            "name": f"auto-follow-assistant-{uuid4().hex[:8]}",
            "space_id": space_id,
        },
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _set_notification_policy(
    client,
    bearer_token: str,
    *,
    allow_assistants: bool,
    allow_apps: bool,
) -> None:
    response = await client.put(
        "/api/v1/admin/api-keys/notification-policy",
        json={
            "enabled": True,
            "allow_auto_follow_published_assistants": allow_assistants,
            "allow_auto_follow_published_apps": allow_apps,
        },
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 200, response.text


async def _create_app_id(client, bearer_token: str, space_id: str) -> str:
    response = await client.post(
        f"/api/v1/spaces/{space_id}/applications/apps/",
        json={"name": f"auto-follow-app-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    if response.status_code == 400 and "No transcription model available" in response.text:
        pytest.skip("App creation requires a transcription model in this test environment.")
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_assistant_auto_follows_when_user_and_policy_allow(
    client,
    default_user_token,
):
    space_id = await _create_space_id(client, default_user_token)
    assistant_id = await _create_assistant_id(client, default_user_token, space_id)
    await _set_notification_policy(
        client,
        default_user_token,
        allow_assistants=True,
        allow_apps=False,
    )

    prefs_response = await client.put(
        "/api/v1/api-keys/notification-preferences",
        json={
            "enabled": True,
            "days_before_expiry": [14, 7, 1],
            "auto_follow_published_assistants": True,
            "auto_follow_published_apps": False,
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert prefs_response.status_code == 200, prefs_response.text

    publish_response = await client.post(
        f"/api/v1/assistants/{assistant_id}/publish/?published=true",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert publish_response.status_code == 200, publish_response.text
    assert publish_response.json()["published"] is True

    subscriptions_response = await client.get(
        "/api/v1/api-keys/notification-subscriptions",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert subscriptions_response.status_code == 200, subscriptions_response.text
    items = subscriptions_response.json()["items"]
    assert {
        (item["target_type"], item["target_id"])
        for item in items
    } >= {("assistant", assistant_id)}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_notification_preferences_apply_policy_gates_and_persist(
    client,
    default_user_token,
):
    await _set_notification_policy(
        client,
        default_user_token,
        allow_assistants=True,
        allow_apps=False,
    )

    update_response = await client.put(
        "/api/v1/api-keys/notification-preferences",
        json={
            "enabled": True,
            "days_before_expiry": [14, 7, 1],
            "auto_follow_published_assistants": True,
            "auto_follow_published_apps": True,
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert update_response.status_code == 200, update_response.text
    updated = update_response.json()
    assert updated["enabled"] is True
    assert updated["auto_follow_published_assistants"] is True
    assert updated["auto_follow_published_apps"] is False

    current_response = await client.get(
        "/api/v1/api-keys/notification-preferences",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert current_response.status_code == 200, current_response.text
    current = current_response.json()
    assert current["enabled"] is True
    assert current["auto_follow_published_assistants"] is True
    assert current["auto_follow_published_apps"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_assistant_does_not_auto_follow_when_opt_out(
    client,
    default_user_token,
):
    space_id = await _create_space_id(client, default_user_token)
    assistant_id = await _create_assistant_id(client, default_user_token, space_id)
    await _set_notification_policy(
        client,
        default_user_token,
        allow_assistants=True,
        allow_apps=False,
    )

    prefs_response = await client.put(
        "/api/v1/api-keys/notification-preferences",
        json={
            "enabled": True,
            "days_before_expiry": [14, 7, 1],
            "auto_follow_published_assistants": False,
            "auto_follow_published_apps": False,
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert prefs_response.status_code == 200, prefs_response.text

    publish_response = await client.post(
        f"/api/v1/assistants/{assistant_id}/publish/?published=true",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert publish_response.status_code == 200, publish_response.text

    subscriptions_response = await client.get(
        "/api/v1/api-keys/notification-subscriptions",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert subscriptions_response.status_code == 200, subscriptions_response.text
    items = subscriptions_response.json()["items"]
    assert ("assistant", assistant_id) not in {
        (item["target_type"], item["target_id"])
        for item in items
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_assistant_auto_follow_is_idempotent_for_same_target(
    client,
    default_user_token,
):
    space_id = await _create_space_id(client, default_user_token)
    assistant_id = await _create_assistant_id(client, default_user_token, space_id)
    await _set_notification_policy(
        client,
        default_user_token,
        allow_assistants=True,
        allow_apps=False,
    )
    prefs_response = await client.put(
        "/api/v1/api-keys/notification-preferences",
        json={
            "enabled": True,
            "days_before_expiry": [14, 7, 1],
            "auto_follow_published_assistants": True,
            "auto_follow_published_apps": False,
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert prefs_response.status_code == 200, prefs_response.text

    first_publish = await client.post(
        f"/api/v1/assistants/{assistant_id}/publish/?published=true",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert first_publish.status_code == 200, first_publish.text

    second_publish = await client.post(
        f"/api/v1/assistants/{assistant_id}/publish/?published=true",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert second_publish.status_code == 200, second_publish.text

    subscriptions_response = await client.get(
        "/api/v1/api-keys/notification-subscriptions",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert subscriptions_response.status_code == 200, subscriptions_response.text
    items = subscriptions_response.json()["items"]
    matches = [
        item
        for item in items
        if item["target_type"] == "assistant" and item["target_id"] == assistant_id
    ]
    assert len(matches) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_app_auto_follows_when_user_and_policy_allow(
    client,
    default_user_token,
):
    space_id = await _create_space_id(client, default_user_token)
    await _set_notification_policy(
        client,
        default_user_token,
        allow_assistants=False,
        allow_apps=True,
    )
    app_id = await _create_app_id(client, default_user_token, space_id)

    prefs_response = await client.put(
        "/api/v1/api-keys/notification-preferences",
        json={
            "enabled": True,
            "days_before_expiry": [21, 14, 7],
            "auto_follow_published_assistants": False,
            "auto_follow_published_apps": True,
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert prefs_response.status_code == 200, prefs_response.text

    publish_response = await client.post(
        f"/api/v1/apps/{app_id}/publish/?published=true",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert publish_response.status_code == 200, publish_response.text
    assert publish_response.json()["published"] is True

    subscriptions_response = await client.get(
        "/api/v1/api-keys/notification-subscriptions",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert subscriptions_response.status_code == 200, subscriptions_response.text
    items = subscriptions_response.json()["items"]
    assert {
        (item["target_type"], item["target_id"])
        for item in items
    } >= {("app", app_id)}
