"""HTTP/PostgreSQL coverage for the local password-change lifecycle."""

import asyncio
from dataclasses import asdict
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from eneo.authentication.auth_service import AuthService
from eneo.main.exceptions import ErrorCodes
from eneo.users.password import LOCAL_PASSWORD_POLICY
from eneo.users.user_service import UserService


@pytest.mark.integration
async def test_baseline_seed_keeps_real_password_hashing(admin_user):
    from init_db import create_salt_and_hashed_password

    password = "IntegrationPass123!"
    assert AuthService.verify_password(password, admin_user.password)

    # The seed's cached credentials must not escape into later init/auth calls.
    salt, hashed_password = create_salt_and_hashed_password(password)
    assert salt != admin_user.salt
    assert hashed_password != admin_user.password
    assert AuthService.verify_password(password, hashed_password)


@pytest.mark.integration
async def test_seed_refuses_a_password_below_the_local_policy(test_settings):
    import psycopg2

    from init_db import add_tenant_user

    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    try:
        with pytest.raises(SystemExit, match="DEFAULT_USER_PASSWORD"):
            add_tenant_user(
                conn,
                tenant_name=f"short-seed-{uuid4().hex[:8]}",
                quota_limit=1000000,
                user_name="short_seed_user",
                user_email="short-seed@example.com",
                user_password="x" * (LOCAL_PASSWORD_POLICY.min_length - 1),
            )
    finally:
        conn.rollback()
        conn.close()


async def _create_local_user(
    client, super_api_key: str, *, password_change_required: bool | None = None
) -> tuple[str, str]:
    suffix = uuid4().hex[:8]
    tenant_response = await client.post(
        "/api/v1/sysadmin/tenants/",
        json={
            "name": f"password-change-{suffix}",
            "display_name": f"Password change {suffix}",
            "state": "active",
        },
        headers={"X-API-Key": super_api_key},
    )
    assert tenant_response.status_code == 200, tenant_response.text

    email = f"password-change-{suffix}@example.com"
    current_password = "OriginalPassword1!"
    user_response = await client.post(
        "/api/v1/sysadmin/users/",
        json={
            "email": email,
            "username": f"password-change-{suffix}",
            "tenant_id": tenant_response.json()["id"],
            "password": current_password,
            **(
                {}
                if password_change_required is None
                else {"password_change_required": password_change_required}
            ),
        },
        headers={"X-API-Key": super_api_key},
    )
    assert user_response.status_code == 200, user_response.text
    return email, current_password


async def _login(client, *, email: str, password: str):
    return await client.post(
        "/api/v1/users/login/token/",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_password_change_rotates_login_and_rejects_prior_session(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
):
    email, current_password = await _create_local_user(client, super_admin_token)
    new_password = "ReplacementPassword2!"

    login = await _login(client, email=email, password=current_password)
    assert login.status_code == 200, login.text
    old_token = login.json()["access_token"]
    old_auth = {"Authorization": f"Bearer {old_token}"}

    wrong_current = await client.post(
        "/api/v1/users/me/password/",
        json={
            "current_password": "DefinitelyWrong1!",
            "new_password": new_password,
        },
        headers=old_auth,
    )
    assert wrong_current.status_code == 400, wrong_current.text
    assert (
        wrong_current.json()["eneo_error_code"] == ErrorCodes.CURRENT_PASSWORD_INCORRECT
    )

    unchanged_session = await client.get("/api/v1/users/me/", headers=old_auth)
    assert unchanged_session.status_code == 200, unchanged_session.text

    changed = await client.post(
        "/api/v1/users/me/password/",
        json={
            "current_password": current_password,
            "new_password": new_password,
        },
        headers=old_auth,
    )
    assert changed.status_code == 204, changed.text

    stale_session = await client.get("/api/v1/users/me/", headers=old_auth)
    assert stale_session.status_code == 401, stale_session.text

    old_login = await _login(client, email=email, password=current_password)
    assert old_login.status_code == 401, old_login.text

    new_login = await _login(client, email=email, password=new_password)
    assert new_login.status_code == 200, new_login.text
    new_token = new_login.json()["access_token"]

    current_user = await client.get(
        "/api/v1/users/me/",
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert current_user.status_code == 200, current_user.text
    assert current_user.json()["password_change"] == {
        "source": "eneo",
        "policy": asdict(LOCAL_PASSWORD_POLICY),
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_session_invalidation_audit_does_not_claim_external_password_change(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
):
    email, current_password = await _create_local_user(client, super_admin_token)
    login = await _login(client, email=email, password=current_password)
    assert login.status_code == 200, login.text
    auth_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    with patch(
        "eneo.audit.application.audit_service.job_manager.enqueue",
        new_callable=AsyncMock,
    ) as enqueue_audit:
        response = await client.post(
            "/api/v1/users/me/sessions/invalidate/",
            headers=auth_headers,
        )

    assert response.status_code == 204, response.text
    enqueue_audit.assert_awaited_once()
    assert enqueue_audit.await_args is not None
    audit_params = enqueue_audit.await_args.args[2]
    assert audit_params["action"] == "sessions_invalidated"
    assert audit_params["description"] == (
        "Invalidated Eneo sessions at the user's request"
    )
    assert audit_params["metadata"]["authentication_method"] == (
        "user_session_invalidation"
    )
    assert audit_params["metadata"]["success"] is True
    rendered_audit = repr(audit_params).lower()
    assert "external" not in rendered_audit
    assert "password_change" not in rendered_audit


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_changes_with_one_current_password_only_write_once(
    client,
    db_container,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    monkeypatch,
):
    email, current_password = await _create_local_user(client, super_admin_token)
    new_password = "ConcurrentPassword2!"
    login = await _login(client, email=email, password=current_password)
    assert login.status_code == 200, login.text
    auth_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Both requests authenticate and cache version zero before either credential
    # writer acquires the row lock. This reproduces the identity-map race that
    # populate_existing on the SELECT FOR UPDATE is intended to close.
    original_change = UserService.change_local_password
    ready_count = 0
    ready_lock = asyncio.Lock()
    both_ready = asyncio.Event()

    async def synchronized_change(
        service: UserService,
        *,
        user_id,
        current_password: str,
        new_password: str,
    ):
        nonlocal ready_count
        async with ready_lock:
            ready_count += 1
            if ready_count == 2:
                both_ready.set()
        await asyncio.wait_for(both_ready.wait(), timeout=5)
        return await original_change(
            service,
            user_id=user_id,
            current_password=current_password,
            new_password=new_password,
        )

    monkeypatch.setattr(UserService, "change_local_password", synchronized_change)
    payload = {
        "current_password": current_password,
        "new_password": new_password,
    }

    first, second = await asyncio.gather(
        client.post(
            "/api/v1/users/me/password/",
            json=payload,
            headers=auth_headers,
        ),
        client.post(
            "/api/v1/users/me/password/",
            json=payload,
            headers=auth_headers,
        ),
    )

    assert sorted([first.status_code, second.status_code]) == [204, 400]
    rejected = first if first.status_code == 400 else second
    assert rejected.json()["eneo_error_code"] == ErrorCodes.CURRENT_PASSWORD_INCORRECT

    async with db_container() as container:
        stored_user = await container.user_repo().get_user_by_email(email)
        assert stored_user is not None
        assert stored_user.credential_version == 1
        assert AuthService.verify_password(new_password, stored_user.password)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sysadmin_set_password_only_admits_its_own_replacement(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
):
    email, one_time_password = await _create_local_user(client, super_admin_token)
    new_password = "ChosenByTheAccount3!"

    login = await _login(client, email=email, password=one_time_password)
    assert login.status_code == 200, login.text
    pending_auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

    blocked = await client.get("/api/v1/users/tenant/", headers=pending_auth)
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["eneo_error_code"] == ErrorCodes.PASSWORD_CHANGE_REQUIRED
    assert blocked.json()["details"] == {"reason": "admin_set"}

    current_user = await client.get("/api/v1/users/me/", headers=pending_auth)
    assert current_user.status_code == 200, current_user.text
    status = current_user.json()["password_status"]
    assert status["change_required"] is True
    assert status["reason"] == "admin_set"
    assert status["changed_at"] is not None

    changed = await client.post(
        "/api/v1/users/me/password/",
        json={"current_password": one_time_password, "new_password": new_password},
        headers=pending_auth,
    )
    assert changed.status_code == 204, changed.text

    relogin = await _login(client, email=email, password=new_password)
    assert relogin.status_code == 200, relogin.text
    auth = {"Authorization": f"Bearer {relogin.json()['access_token']}"}
    admitted = await client.get("/api/v1/users/tenant/", headers=auth)
    assert admitted.status_code == 200, admitted.text
    current_user = await client.get("/api/v1/users/me/", headers=auth)
    assert current_user.json()["password_status"]["change_required"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sysadmin_can_skip_the_initial_password_change(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
):
    email, password = await _create_local_user(
        client, super_admin_token, password_change_required=False
    )
    login = await _login(client, email=email, password=password)
    assert login.status_code == 200, login.text
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

    admitted = await client.get("/api/v1/users/tenant/", headers=auth)
    assert admitted.status_code == 200, admitted.text
    current_user = await client.get("/api/v1/users/me/", headers=auth)
    assert current_user.json()["password_status"]["change_required"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_password_policy_round_trip(
    client, patch_auth_service_jwt, mock_transcription_models
):
    login = await _login(
        client, email="test@example.com", password="IntegrationPass123!"
    )
    assert login.status_code == 200, login.text
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

    current = await client.get("/api/v1/admin/password-policy", headers=auth)
    assert current.status_code == 200, current.text
    assert current.json() == {"max_age_days": None}

    updated = await client.patch(
        "/api/v1/admin/password-policy",
        json={"max_age_days": 30},
        headers=auth,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json() == {"max_age_days": 30}

    unknown_field = await client.patch(
        "/api/v1/admin/password-policy",
        json={"rotate_every": 30},
        headers=auth,
    )
    assert unknown_field.status_code == 422, unknown_field.text

    # Admin-set passwords are always one-time; no tenant can switch that off.
    one_time_rule = await client.patch(
        "/api/v1/admin/password-policy",
        json={"require_change_after_admin_set": False},
        headers=auth,
    )
    assert one_time_rule.status_code == 422, one_time_rule.text
    unchanged = await client.get("/api/v1/admin/password-policy", headers=auth)
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json() == updated.json()

    reset = await client.patch(
        "/api/v1/admin/password-policy",
        json={"max_age_days": None},
        headers=auth,
    )
    assert reset.status_code == 200, reset.text
    assert reset.json() == {"max_age_days": None}

    # The expiry shows up on the account once the policy carries a maximum age.
    await client.patch(
        "/api/v1/admin/password-policy", json={"max_age_days": 90}, headers=auth
    )
    me = await client.get("/api/v1/users/me/", headers=auth)
    assert me.status_code == 200, me.text
    assert me.json()["password_status"]["expires_at"] is not None
    assert me.json()["password_status"]["change_required"] is False
    await client.patch(
        "/api/v1/admin/password-policy", json={"max_age_days": None}, headers=auth
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_disjoint_policy_patches_both_land(
    client, patch_auth_service_jwt, mock_transcription_models
):
    """Two admins patching different keys at once must not undo each other.

    Session A writes ``max_expiration_days`` and keeps its transaction (and
    the row lock) open while session B writes ``rotation_grace_hours``. B can
    only commit after A, so a merge computed from a pre-read snapshot would
    write A's key back to its old value. The password policy shares the same
    merge (``TenantRepository._merge_policy_column``).
    """
    import sqlalchemy as sa

    from eneo.database.database import sessionmanager
    from eneo.tenants.tenant_repo import TenantRepository

    async with sessionmanager.session() as session, session.begin():
        tenant_id = (
            await session.execute(
                sa.text("SELECT tenant_id FROM users WHERE email = :email"),
                {"email": "test@example.com"},
            )
        ).scalar_one()

    async def patch_in_own_session(updates: dict) -> None:
        async with sessionmanager.session() as session, session.begin():
            await TenantRepository(session).update_api_key_policy(tenant_id, updates)

    async def wait_until_blocked_on_lock(racer: asyncio.Task) -> None:
        for _ in range(200):
            if racer.done():
                racer.result()
                raise AssertionError("racer finished before the lock was released")
            async with sessionmanager.session() as session, session.begin():
                waiting = (
                    await session.execute(
                        sa.text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname = current_database() "
                            "AND wait_event_type = 'Lock'"
                        )
                    )
                ).scalar_one()
            if waiting:
                return
            await asyncio.sleep(0.05)
        raise AssertionError("racer never blocked on the tenant row lock")

    async with sessionmanager.session() as session_a, session_a.begin():
        await TenantRepository(session_a).update_api_key_policy(
            tenant_id, {"max_expiration_days": 30}
        )
        racer = asyncio.create_task(patch_in_own_session({"rotation_grace_hours": 12}))
        await wait_until_blocked_on_lock(racer)
    await asyncio.wait_for(racer, timeout=10)

    async with sessionmanager.session() as session, session.begin():
        policy = (
            await session.execute(
                sa.text("SELECT api_key_policy FROM tenants WHERE id = :id"),
                {"id": tenant_id},
            )
        ).scalar_one()
    assert policy["max_expiration_days"] == 30
    assert policy["rotation_grace_hours"] == 12


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expired_password_only_admits_its_own_replacement(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
):
    from datetime import datetime, timedelta, timezone

    import sqlalchemy as sa

    from eneo.database.database import sessionmanager

    email, old_password = await _create_local_user(
        client, super_admin_token, password_change_required=False
    )
    # The tenant rotates after 30 days and this password is 31 days old.
    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.text(
                "UPDATE tenants SET password_policy = password_policy || "
                "'{\"max_age_days\": 30}'::jsonb "
                "WHERE id = (SELECT tenant_id FROM users WHERE email = :email)"
            ),
            {"email": email},
        )
        await session.execute(
            sa.text(
                "UPDATE users SET password_changed_at = :changed_at WHERE email = :email"
            ),
            {
                "email": email,
                "changed_at": datetime.now(timezone.utc) - timedelta(days=31),
            },
        )

    login = await _login(client, email=email, password=old_password)
    assert login.status_code == 200, login.text
    expired_auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

    blocked = await client.get("/api/v1/users/tenant/", headers=expired_auth)
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["details"] == {"reason": "expired"}
    me = await client.get("/api/v1/users/me/", headers=expired_auth)
    assert me.json()["password_status"]["reason"] == "expired"

    changed = await client.post(
        "/api/v1/users/me/password/",
        json={"current_password": old_password, "new_password": "FreshPassword4!xx"},
        headers=expired_auth,
    )
    assert changed.status_code == 204, changed.text
    relogin = await _login(client, email=email, password="FreshPassword4!xx")
    auth = {"Authorization": f"Bearer {relogin.json()['access_token']}"}
    admitted = await client.get("/api/v1/users/tenant/", headers=auth)
    assert admitted.status_code == 200, admitted.text
    status = (await client.get("/api/v1/users/me/", headers=auth)).json()[
        "password_status"
    ]
    assert status["change_required"] is False
    assert status["expires_at"] is not None
