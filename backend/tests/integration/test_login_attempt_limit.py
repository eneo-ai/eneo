"""HTTP coverage for the failed password-login limit, with PostgreSQL and Redis."""

import asyncio
from uuid import uuid4

import pytest

from eneo.audit.infrastructure.rate_limiting import RateLimitServiceUnavailableError
from eneo.authentication.login_attempts import LOGIN_ATTEMPT_LIMIT
from eneo.users import user_router

PASSWORD = "OriginalPassword1!"
LIMIT = LOGIN_ATTEMPT_LIMIT.max_requests


async def _create_local_user(client, super_api_key: str) -> str:
    suffix = uuid4().hex[:8]
    tenant = await client.post(
        "/api/v1/sysadmin/tenants/",
        json={
            "name": f"login-limit-{suffix}",
            "display_name": f"Login limit {suffix}",
            "state": "active",
        },
        headers={"X-API-Key": super_api_key},
    )
    assert tenant.status_code == 200, tenant.text
    email = f"login-limit-{suffix}@example.com"
    user = await client.post(
        "/api/v1/sysadmin/users/",
        json={
            "email": email,
            "username": f"login-limit-{suffix}",
            "tenant_id": tenant.json()["id"],
            "password": PASSWORD,
        },
        headers={"X-API-Key": super_api_key},
    )
    assert user.status_code == 200, user.text
    return email


async def _login(client, email: str, password: str):
    return await client.post(
        "/api/v1/users/login/token/",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_failed_logins_count_down_and_then_block_even_the_right_password(
    client, super_admin_token, patch_auth_service_jwt, mock_transcription_models
):
    email = await _create_local_user(client, super_admin_token)

    for used in range(1, LIMIT + 1):
        failed = await _login(client, email, "WrongPassword1!")
        assert failed.status_code == 401, failed.text
        body = failed.json()
        assert body["code"] == "invalid_credentials"
        assert body["attempts_remaining"] == LIMIT - used

    blocked = await _login(client, email, PASSWORD)
    assert blocked.status_code == 429, blocked.text
    body = blocked.json()
    assert body["code"] == "too_many_login_attempts"
    assert body["attempts_remaining"] == 0
    retry_after = body["retry_after_seconds"]
    assert 0 < retry_after <= LOGIN_ATTEMPT_LIMIT.window_seconds
    assert blocked.headers["Retry-After"] == str(retry_after)
    assert "access_token" not in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_successful_login_restores_the_full_allowance(
    client, super_admin_token, patch_auth_service_jwt, mock_transcription_models
):
    email = await _create_local_user(client, super_admin_token)

    for _ in range(LIMIT - 1):
        assert (await _login(client, email, "WrongPassword1!")).status_code == 401

    assert (await _login(client, email, PASSWORD)).status_code == 200

    failed = await _login(client, email, "WrongPassword1!")
    assert failed.status_code == 401, failed.text
    assert failed.json()["attempts_remaining"] == LIMIT - 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unknown_and_known_names_are_counted_alike_and_separately(
    client, super_admin_token, patch_auth_service_jwt, mock_transcription_models
):
    email = await _create_local_user(client, super_admin_token)
    unknown = f"nobody-{uuid4().hex[:8]}@example.com"

    known_failure = await _login(client, email, "WrongPassword1!")
    unknown_failure = await _login(client, unknown, "WrongPassword1!")

    assert known_failure.status_code == unknown_failure.status_code == 401
    hidden = {"request_id"}
    assert {k: v for k, v in known_failure.json().items() if k not in hidden} == {
        k: v for k, v in unknown_failure.json().items() if k not in hidden
    }
    assert known_failure.json()["attempts_remaining"] == LIMIT - 1

    # Case and surrounding spaces address the same account.
    variant = await _login(client, f"  {email.upper()} ", "WrongPassword1!")
    assert variant.status_code in {401, 422}, variant.text
    if variant.status_code == 401:
        assert variant.json()["attempts_remaining"] == LIMIT - 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_guesses_cannot_exceed_the_limit(
    client, super_admin_token, patch_auth_service_jwt, mock_transcription_models
):
    email = await _create_local_user(client, super_admin_token)

    responses = await asyncio.gather(
        *(_login(client, email, f"WrongPassword{n}!") for n in range(LIMIT * 3))
    )

    statuses = sorted(response.status_code for response in responses)
    assert statuses.count(401) == LIMIT
    assert statuses.count(429) == LIMIT * 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_login_still_works_when_the_limiter_is_unavailable(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    monkeypatch,
):
    email = await _create_local_user(client, super_admin_token)

    async def unavailable(*_args, **_kwargs):
        raise RateLimitServiceUnavailableError(ConnectionError("redis is down"))

    monkeypatch.setattr(user_router, "count_login_attempt", unavailable)

    failed = await _login(client, email, "WrongPassword1!")
    assert failed.status_code == 401, failed.text
    assert "attempts_remaining" not in failed.json()

    assert (await _login(client, email, PASSWORD)).status_code == 200
