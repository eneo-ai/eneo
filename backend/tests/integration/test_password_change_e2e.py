"""HTTP/PostgreSQL coverage for the local password-change lifecycle."""

import asyncio
from uuid import uuid4

import pytest

from eneo.authentication.auth_service import AuthService
from eneo.main.exceptions import ErrorCodes
from eneo.users.user_service import UserService


async def _create_local_user(client, super_api_key: str) -> tuple[str, str]:
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
        "policy": {"min_length": 15, "max_bytes": 72},
    }


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
