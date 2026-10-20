"""The What's new markers are personal, idempotent and session-only."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Literal

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from eneo.whats_new.whats_new_repo import WhatsNewRepository


@pytest.mark.integration
@pytest.mark.parametrize("resolution", ["seen", "announced"])
async def test_reminder_persists_for_24_hours_and_is_consumed(
    api_client, bearer_token, resolution
):
    headers = {"Authorization": f"Bearer {bearer_token}"}
    before = datetime.now(timezone.utc)
    snoozed = await api_client.put(
        "/api/v1/whats-new/snooze/", headers=headers, json={"version": "2.3.0"}
    )
    assert snoozed.status_code == 200
    state = snoozed.json()
    reminder = datetime.fromisoformat(state["remind_after"].replace("Z", "+00:00"))
    assert (
        before + timedelta(hours=24)
        <= reminder
        <= datetime.now(timezone.utc) + timedelta(hours=24)
    )
    assert state["seen_version"] is None
    assert state["announced_version"] == "2.3.0"
    persisted = await api_client.get("/api/v1/whats-new/state/", headers=headers)
    assert persisted.json() == state
    resolved = await api_client.put(
        f"/api/v1/whats-new/{resolution}/", headers=headers, json={"version": "2.3.0"}
    )
    assert resolved.json()["remind_after"] is None
    if resolution == "seen":
        stale = await api_client.put(
            "/api/v1/whats-new/snooze/", headers=headers, json={"version": "2.3.0"}
        )
        assert stale.json()["remind_after"] is None


@pytest.mark.integration
async def test_older_tabs_cannot_replace_or_cancel_a_newer_reminder(
    api_client, bearer_token
):
    headers = {"Authorization": f"Bearer {bearer_token}"}
    current = await api_client.put(
        "/api/v1/whats-new/snooze/", headers=headers, json={"version": "2.3.0"}
    )
    for action in ("snooze", "announced", "seen"):
        stale = await api_client.put(
            f"/api/v1/whats-new/{action}/", headers=headers, json={"version": "2.2.0"}
        )
        assert stale.json()["announced_version"] == "2.3.0"
        assert stale.json()["remind_after"] == current.json()["remind_after"]
    newer = await api_client.put(
        "/api/v1/whats-new/announced/", headers=headers, json={"version": "2.4.0"}
    )
    assert newer.json()["announced_version"] == "2.4.0"
    assert newer.json()["remind_after"] is None


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
    assert initial.json() == {
        "seen_version": None,
        "announced_version": None,
        "remind_after": None,
    }

    # The announcement is shown before the page is ever opened.
    announced = await api_client.put(
        "/api/v1/whats-new/announced/", headers=headers, json={"version": "2.2.0"}
    )
    assert announced.status_code == 200
    assert announced.json() == {
        "seen_version": None,
        "announced_version": "2.2.0",
        "remind_after": None,
    }

    seen = await api_client.put(
        "/api/v1/whats-new/seen/", headers=headers, json={"version": "2.2.0"}
    )
    assert seen.json() == {
        "seen_version": "2.2.0",
        "announced_version": "2.2.0",
        "remind_after": None,
    }

    # A later release overwrites the single row instead of adding one.
    later = await api_client.put(
        "/api/v1/whats-new/seen/", headers=headers, json={"version": "2.3.0"}
    )
    assert later.json() == {
        "seen_version": "2.3.0",
        "announced_version": "2.2.0",
        "remind_after": None,
    }

    # An older frontend build cannot move a marker backwards.
    older = await api_client.put(
        "/api/v1/whats-new/seen/", headers=headers, json={"version": "2.2.0"}
    )
    assert older.json()["seen_version"] == "2.3.0"

    final = await api_client.get("/api/v1/whats-new/state/", headers=headers)
    assert final.json() == {
        "seen_version": "2.3.0",
        "announced_version": "2.2.0",
        "remind_after": None,
    }


@pytest.mark.integration
async def test_markers_reject_malformed_versions(api_client, bearer_token):
    headers = {"Authorization": f"Bearer {bearer_token}"}
    for path in (
        "/api/v1/whats-new/seen/",
        "/api/v1/whats-new/announced/",
        "/api/v1/whats-new/snooze/",
    ):
        response = await api_client.put(
            path, headers=headers, json={"version": "v2.2.0"}
        )
        assert response.status_code == 422


@pytest.mark.integration
async def test_rc_markers_survive_stale_clients_and_advance_to_final(
    api_client, bearer_token, monkeypatch
):
    from eneo.main.config import get_settings

    headers = {"Authorization": f"Bearer {bearer_token}"}
    for version in ("2.3.0-rc.1", "2.3.0-rc.2", "2.3.0"):
        monkeypatch.setattr(get_settings(), "app_version", version)
        for marker in ("seen", "announced"):
            path = f"/api/v1/whats-new/{marker}/"
            current = await api_client.put(
                path, headers=headers, json={"version": version}
            )
            assert current.status_code == 200
            assert current.json()[f"{marker}_version"] == version
            # RC0 used the final content id. It must not poison later RC progress.
            stale = await api_client.put(
                path, headers=headers, json={"version": "2.3.0"}
            )
            assert stale.status_code == 200
            assert stale.json()[f"{marker}_version"] == version


@pytest.mark.integration
async def test_markers_are_session_only(api_client, admin_user_api_key):
    headers = {"X-API-Key": admin_user_api_key.key}

    read = await api_client.get("/api/v1/whats-new/state/", headers=headers)
    assert read.status_code == 403

    for path in (
        "/api/v1/whats-new/seen/",
        "/api/v1/whats-new/announced/",
        "/api/v1/whats-new/snooze/",
    ):
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
    assert reset.json() == {
        "seen_version": None,
        "announced_version": None,
        "remind_after": None,
    }

    state = await api_client.get("/api/v1/whats-new/state/", headers=headers)
    assert state.json() == {
        "seen_version": None,
        "announced_version": None,
        "remind_after": None,
    }


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


@pytest.mark.integration
@pytest.mark.parametrize("marker", ["seen_version", "announced_version"])
@pytest.mark.parametrize("existing", [False, True], ids=["first-write", "existing-row"])
async def test_concurrent_older_write_cannot_replace_a_newer_marker(
    db_session,
    default_user,
    marker: Literal["seen_version", "announced_version"],
    existing: bool,
):
    """Use two real transactions and wait for an observed database lock.

    The older writer reads while the newer writer has not committed. The
    former read-then-upsert path would resume and overwrite that newer value.
    """
    user_id = default_user.id
    async with db_session() as session:
        repo = WhatsNewRepository(session)
        await repo.reset(user_id)
        if existing:
            await repo.mark_seen(user_id, "2.1.0")
            await repo.mark_announced(user_id, "2.1.0")

    writer_pid: asyncio.Queue[int] = asyncio.Queue()

    async def write_older():
        async with db_session() as session:
            writer_pid.put_nowait(
                (await session.execute(sa.text("SELECT pg_backend_pid()"))).scalar_one()
            )
            repo = WhatsNewRepository(session)
            write = repo.mark_seen if marker == "seen_version" else repo.mark_announced
            return await write(user_id, "2.2.0")

    older = None
    try:
        async with db_session() as session:
            repo = WhatsNewRepository(session)
            write = repo.mark_seen if marker == "seen_version" else repo.mark_announced
            await write(user_id, "2.3.0")
            older = asyncio.create_task(write_older())
            async with asyncio.timeout(5):
                pid = await writer_pid.get()
                while not (
                    await session.execute(
                        sa.text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                        {"pid": pid},
                    )
                ).scalar_one():
                    await asyncio.sleep(0.01)
        result = await asyncio.wait_for(older, timeout=5)
        assert result.model_dump()[marker] == "2.3.0"
        async with db_session() as session:
            persisted = await WhatsNewRepository(session).get_state(user_id)
            assert persisted.model_dump()[marker] == "2.3.0"
            other = "announced_version" if marker == "seen_version" else "seen_version"
            assert persisted.model_dump()[other] == ("2.1.0" if existing else None)
    finally:
        if older is not None:
            older.cancel()
            await asyncio.gather(older, return_exceptions=True)
