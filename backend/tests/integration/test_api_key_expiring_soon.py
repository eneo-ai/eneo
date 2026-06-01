"""Integration tests for the GET /api/v1/api-keys/expiring-soon endpoint.

These tests cover the functional behaviour that previously had no
coverage: the `days` look-ahead window, severity classification,
inclusion of recently-expired keys via the lookback window, exclusion
of revoked keys, and `mode=subscribed` filtering against followed
targets (key + assistant scope).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def _iso(offset_days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=offset_days)).isoformat()


async def _create_tenant_key(
    client,
    bearer_token: str,
    *,
    name: str,
    expires_at_iso: str,
) -> str:
    response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": name,
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "tenant",
            "expires_at": expires_at_iso,
        },
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["api_key"]["id"]


async def _create_assistant_scoped_key(
    client,
    bearer_token: str,
    *,
    name: str,
    assistant_id: str,
    expires_at_iso: str,
) -> str:
    response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": name,
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "assistant",
            "scope_id": assistant_id,
            "expires_at": expires_at_iso,
        },
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["api_key"]["id"]


async def _create_space_and_assistant(client, bearer_token: str) -> tuple[str, str]:
    space_response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"expiring-space-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert space_response.status_code == 201, space_response.text
    space_id = space_response.json()["id"]

    assistant_response = await client.post(
        "/api/v1/assistants/",
        json={
            "name": f"expiring-assistant-{uuid4().hex[:8]}",
            "space_id": space_id,
        },
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert assistant_response.status_code == 200, assistant_response.text
    return space_id, assistant_response.json()["id"]


async def _enable_notifications(client, bearer_token: str) -> None:
    response = await client.put(
        "/api/v1/api-keys/notification-preferences",
        json={
            "enabled": True,
            "days_before_expiry": [30],
            "auto_follow_published_assistants": False,
            "auto_follow_published_apps": False,
        },
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 200, response.text


async def _follow_target(
    client, bearer_token: str, *, target_type: str, target_id: str
) -> None:
    response = await client.put(
        f"/api/v1/api-keys/notification-subscriptions/{target_type}/{target_id}",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 200, response.text


async def _fetch_expiring(
    client,
    bearer_token: str,
    *,
    days: int = 30,
    mode: str = "all",
) -> dict:
    response = await client.get(
        f"/api/v1/api-keys/expiring-soon?days={days}&mode={mode}",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _ids(summary: dict) -> set[str]:
    return {item["id"] for item in summary["items"]}


def _by_id(summary: dict) -> dict[str, dict]:
    return {item["id"]: item for item in summary["items"]}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expiring_soon_filters_by_days_window(client, default_user_token):
    """The `days` query param defines an upper bound on which keys appear."""
    soon_id = await _create_tenant_key(
        client,
        default_user_token,
        name=f"soon-{uuid4().hex[:6]}",
        expires_at_iso=_iso(5),
    )
    mid_id = await _create_tenant_key(
        client,
        default_user_token,
        name=f"mid-{uuid4().hex[:6]}",
        expires_at_iso=_iso(20),
    )
    far_id = await _create_tenant_key(
        client,
        default_user_token,
        name=f"far-{uuid4().hex[:6]}",
        expires_at_iso=_iso(60),
    )

    narrow = await _fetch_expiring(client, default_user_token, days=10)
    narrow_ids = _ids(narrow)
    assert soon_id in narrow_ids
    assert mid_id not in narrow_ids
    assert far_id not in narrow_ids

    medium = await _fetch_expiring(client, default_user_token, days=30)
    medium_ids = _ids(medium)
    assert {soon_id, mid_id} <= medium_ids
    assert far_id not in medium_ids

    wide = await _fetch_expiring(client, default_user_token, days=80)
    assert {soon_id, mid_id, far_id} <= _ids(wide)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expiring_soon_severity_classification(client, default_user_token):
    """Severity tiers: expired (≤now) → urgent (≤3d) → warning (≤14d) → notice (>14d)."""
    expired_id = await _create_tenant_key(
        client,
        default_user_token,
        name=f"expired-{uuid4().hex[:6]}",
        expires_at_iso=_iso(-1),
    )
    urgent_id = await _create_tenant_key(
        client,
        default_user_token,
        name=f"urgent-{uuid4().hex[:6]}",
        expires_at_iso=_iso(2),
    )
    warning_id = await _create_tenant_key(
        client,
        default_user_token,
        name=f"warning-{uuid4().hex[:6]}",
        expires_at_iso=_iso(10),
    )
    notice_id = await _create_tenant_key(
        client,
        default_user_token,
        name=f"notice-{uuid4().hex[:6]}",
        expires_at_iso=_iso(25),
    )

    summary = await _fetch_expiring(client, default_user_token, days=30)
    by_id = _by_id(summary)

    assert by_id[expired_id]["severity"] == "expired"
    assert by_id[urgent_id]["severity"] == "urgent"
    assert by_id[warning_id]["severity"] == "warning"
    assert by_id[notice_id]["severity"] == "notice"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expiring_soon_includes_recently_expired_keys(client, default_user_token):
    """Keys expired within the lookback window (~30d) still appear."""
    recently_expired_id = await _create_tenant_key(
        client,
        default_user_token,
        name=f"recently-expired-{uuid4().hex[:6]}",
        expires_at_iso=_iso(-3),
    )

    summary = await _fetch_expiring(client, default_user_token, days=14)
    item_ids = _ids(summary)
    assert recently_expired_id in item_ids
    by_id = _by_id(summary)
    assert by_id[recently_expired_id]["severity"] == "expired"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expiring_soon_excludes_revoked_keys(client, default_user_token):
    """Revoked keys must not appear even if their expires_at is in window."""
    key_id = await _create_tenant_key(
        client,
        default_user_token,
        name=f"to-revoke-{uuid4().hex[:6]}",
        expires_at_iso=_iso(5),
    )

    before = await _fetch_expiring(client, default_user_token, days=30)
    assert key_id in _ids(before), "key should be visible before revocation"

    revoke_response = await client.post(
        f"/api/v1/api-keys/{key_id}/revoke",
        json={"reason_code": "security_concern", "reason_text": "test cleanup"},
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert revoke_response.status_code == 200, revoke_response.text

    after = await _fetch_expiring(client, default_user_token, days=30)
    assert key_id not in _ids(after)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expiring_soon_subscribed_mode_filters_followed_keys(
    client, default_user_token
):
    """`mode=subscribed` returns only keys the user explicitly follows."""
    followed_id = await _create_tenant_key(
        client,
        default_user_token,
        name=f"followed-{uuid4().hex[:6]}",
        expires_at_iso=_iso(7),
    )
    unfollowed_id = await _create_tenant_key(
        client,
        default_user_token,
        name=f"unfollowed-{uuid4().hex[:6]}",
        expires_at_iso=_iso(7),
    )

    await _enable_notifications(client, default_user_token)
    await _follow_target(
        client,
        default_user_token,
        target_type="key",
        target_id=followed_id,
    )

    all_mode = await _fetch_expiring(client, default_user_token, days=30, mode="all")
    assert {followed_id, unfollowed_id} <= _ids(all_mode)

    subscribed = await _fetch_expiring(
        client, default_user_token, days=30, mode="subscribed"
    )
    subscribed_ids = _ids(subscribed)
    assert followed_id in subscribed_ids
    assert unfollowed_id not in subscribed_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expiring_soon_subscribed_mode_returns_empty_without_subscriptions(
    client, default_user_token
):
    """With notifications enabled but no subscriptions, subscribed-mode is empty."""
    await _create_tenant_key(
        client,
        default_user_token,
        name=f"orphan-{uuid4().hex[:6]}",
        expires_at_iso=_iso(7),
    )
    await _enable_notifications(client, default_user_token)

    summary = await _fetch_expiring(
        client, default_user_token, days=30, mode="subscribed"
    )
    assert summary["items"] == []
    assert summary["total_count"] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expiring_soon_accepts_days_up_to_365(client, default_user_token):
    """The days look-ahead must accept up to 365d to match tenant policy max."""
    far_future_id = await _create_tenant_key(
        client,
        default_user_token,
        name=f"far-future-{uuid4().hex[:6]}",
        expires_at_iso=_iso(200),
    )

    summary = await _fetch_expiring(client, default_user_token, days=365)
    assert far_future_id in _ids(summary)

    rejected = await client.get(
        "/api/v1/api-keys/expiring-soon?days=366&mode=all",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert rejected.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expiring_soon_subscribed_mode_via_assistant_scope(
    client, default_user_token
):
    """Following an assistant scope surfaces every key scoped to that assistant."""
    _, assistant_id = await _create_space_and_assistant(client, default_user_token)
    scoped_id = await _create_assistant_scoped_key(
        client,
        default_user_token,
        name=f"scoped-{uuid4().hex[:6]}",
        assistant_id=assistant_id,
        expires_at_iso=_iso(7),
    )
    other_id = await _create_tenant_key(
        client,
        default_user_token,
        name=f"other-{uuid4().hex[:6]}",
        expires_at_iso=_iso(7),
    )

    await _enable_notifications(client, default_user_token)
    await _follow_target(
        client,
        default_user_token,
        target_type="assistant",
        target_id=assistant_id,
    )

    summary = await _fetch_expiring(
        client, default_user_token, days=30, mode="subscribed"
    )
    subscribed_ids = _ids(summary)
    assert scoped_id in subscribed_ids
    assert other_id not in subscribed_ids
