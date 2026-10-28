"""The browser session end to end, with PostgreSQL and Redis.

The client talks to http://test.local and httpx does not send Secure cookies
over http, so each request carries the session in an explicit Cookie header.
"""

from collections.abc import Iterator
from uuid import uuid4

import pytest

from eneo.authentication.browser_session import session_generation
from eneo.authentication.login_attempts import LOGIN_ATTEMPT_LIMIT
from eneo.main.config import Settings, get_settings, set_settings
from tests.unit.browser_session_test_utils import expected_set_cookie

PASSWORD = "OriginalPassword1!"
WRONG = "WrongPassword1!"
SESSION = "__Host-eneo_web"
GENERATION = "Eneo-Session-Generation"
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
SESSION_LOGIN = "/api/v1/auth/session/password/"
TOKEN_LOGIN = "/api/v1/users/login/token/"
FORM = {"Content-Type": "application/x-www-form-urlencoded"}
TICKETS = "/api/v1/module-auth/tickets/"
TICKET = {"module_key": "no-such-module", "redirect_uri": "https://m.example/cb"}


@pytest.fixture
def browser_session_on() -> Iterator[Settings]:
    original = get_settings()
    set_settings(
        original.model_copy(
            update={"browser_session_enabled": True, "environment": "production"}
        )
    )
    try:
        yield original
    finally:
        set_settings(original)


async def _create_local_user(
    client, super_api_key: str, *, must_change_password: bool = False
) -> str:
    suffix = uuid4().hex[:8]
    tenant = await client.post(
        "/api/v1/sysadmin/tenants/",
        json={
            "name": f"browser-session-{suffix}",
            "display_name": f"Browser session {suffix}",
            "state": "active",
        },
        headers={"X-API-Key": super_api_key},
    )
    assert tenant.status_code == 200, tenant.text
    email = f"browser-session-{suffix}@example.com"
    user = await client.post(
        "/api/v1/sysadmin/users/",
        json={
            "email": email,
            "username": f"browser-session-{suffix}",
            "tenant_id": tenant.json()["id"],
            "password": PASSWORD,
            "password_change_required": must_change_password,
        },
        headers={"X-API-Key": super_api_key},
    )
    assert user.status_code == 200, user.text
    return email


async def _login(client, path: str, email: str, password: str):
    return await client.post(
        path,
        data={"username": email, "password": password},
        headers=FORM | SAME_ORIGIN,
    )


def _session_token(response) -> str:
    [cookie] = response.headers.get_list("set-cookie")
    token = cookie.removeprefix(f"{SESSION}=").split(";", 1)[0]
    max_age = int(cookie.split("Max-Age=", 1)[1].split(";", 1)[0])
    assert max_age > 0
    assert cookie == expected_set_cookie(SESSION, token, max_age, production=True)
    return token


def _without_request_id(response) -> dict:
    body = response.json()
    body.pop("request_id", None)
    return body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_session_cookie_signs_the_browser_in_and_out(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    email = await _create_local_user(client, super_admin_token)

    signed_in = await _login(client, SESSION_LOGIN, email, PASSWORD)
    assert signed_in.status_code == 204, signed_in.text
    assert signed_in.content == b""
    token = _session_token(signed_in)
    cookie = {"Cookie": f"{SESSION}={token}"}
    generation = session_generation(token)

    me = await client.get("/api/v1/users/me/", headers=cookie | SAME_ORIGIN)
    assert me.status_code == 200, me.text
    assert me.json()["email"] == email
    assert me.headers[GENERATION] == generation

    probe = await client.get("/api/v1/auth/session/", headers=cookie | SAME_ORIGIN)
    assert probe.status_code == 204, probe.text
    assert probe.headers[GENERATION] == generation

    cross_site = await client.get(
        "/api/v1/users/me/", headers=cookie | {"Sec-Fetch-Site": "cross-site"}
    )
    assert cross_site.status_code == 401
    assert GENERATION not in cross_site.headers

    # A Session-only endpoint admits the cookie session (no API key behind it)
    # and reaches the broker, which knows no such module.
    ticket = await client.post(TICKETS, json=TICKET, headers=cookie | SAME_ORIGIN)
    assert ticket.status_code == 404, ticket.text
    # The broker's NotFoundException, not a routing miss (which has no code).
    assert ticket.json()["eneo_error_code"] == 9000
    assert ticket.headers[GENERATION] == generation
    anonymous = await client.post(TICKETS, json=TICKET, headers=SAME_ORIGIN)
    assert anonymous.status_code == 401

    # A page loaded under another session cannot sign this one out.
    stale = await client.post(
        "/api/v1/auth/session/logout/",
        headers=cookie | SAME_ORIGIN | {GENERATION: session_generation("other")},
    )
    assert stale.status_code == 401
    assert stale.json()["eneo_error_code"] == 9080
    assert stale.headers.get_list("set-cookie") == []
    still_in = await client.get("/api/v1/users/me/", headers=cookie | SAME_ORIGIN)
    assert still_in.status_code == 200

    signed_out = await client.post(
        "/api/v1/auth/session/logout/",
        headers=cookie | SAME_ORIGIN | {GENERATION: generation},
    )
    assert signed_out.status_code == 204
    cleared = signed_out.headers.get_list("set-cookie")
    assert cleared[0].startswith(f'{SESSION}=""; HttpOnly; Max-Age=0; Path=/')


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_password_that_must_be_replaced_still_signs_in(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    # As with /users/login/token/: the session exists, but until the password
    # is replaced only the routes that replacement needs admit it.
    email = await _create_local_user(
        client, super_admin_token, must_change_password=True
    )

    signed_in = await _login(client, SESSION_LOGIN, email, PASSWORD)
    assert signed_in.status_code == 204, signed_in.text
    cookie = {"Cookie": f"{SESSION}={_session_token(signed_in)}"}

    me = await client.get("/api/v1/users/me/", headers=cookie | SAME_ORIGIN)
    assert me.status_code == 200, me.text
    assert me.json()["password_status"]["change_required"] is True
    probe = await client.get("/api/v1/auth/session/", headers=cookie | SAME_ORIGIN)
    assert probe.status_code == 204, probe.text
    blocked = await client.post(TICKETS, json=TICKET, headers=cookie | SAME_ORIGIN)
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["eneo_error_code"] == 9070


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cross_site_form_cannot_sign_the_browser_in(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    email = await _create_local_user(client, super_admin_token)

    refused = await client.post(
        SESSION_LOGIN,
        data={"username": email, "password": PASSWORD},
        headers=FORM | {"Sec-Fetch-Site": "cross-site"},
    )

    assert refused.status_code == 403
    assert refused.json()["code"] == "browser_origin_refused"
    assert refused.headers.get_list("set-cookie") == []
    # Refused before the credentials were checked: no attempt was counted.
    failed = await _login(client, TOKEN_LOGIN, email, WRONG)
    assert failed.json()["attempts_remaining"] == LOGIN_ATTEMPT_LIMIT.max_requests - 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bearer_login_is_unchanged(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    email = await _create_local_user(client, super_admin_token)

    login = await _login(client, TOKEN_LOGIN, email, PASSWORD)
    assert login.status_code == 200, login.text
    assert login.headers.get_list("set-cookie") == []
    bearer = {"Authorization": f"Bearer {login.json()['access_token']}"}

    me = await client.get("/api/v1/users/me/", headers=bearer)
    assert me.status_code == 200
    assert GENERATION not in me.headers
    probe = await client.get("/api/v1/auth/session/", headers=bearer)
    assert probe.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_failed_attempts_count_across_both_login_paths(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    email = await _create_local_user(client, super_admin_token)
    limit = LOGIN_ATTEMPT_LIMIT.max_requests

    for used in range(1, limit + 1):
        path = SESSION_LOGIN if used % 2 else TOKEN_LOGIN
        failed = await _login(client, path, email, WRONG)
        assert failed.status_code == 401, failed.text
        assert failed.json()["attempts_remaining"] == limit - used

    session_blocked = await _login(client, SESSION_LOGIN, email, PASSWORD)
    token_blocked = await _login(client, TOKEN_LOGIN, email, PASSWORD)

    assert session_blocked.status_code == token_blocked.status_code == 429
    assert session_blocked.headers.get_list("set-cookie") == []
    assert session_blocked.headers["Retry-After"]
    body = _without_request_id(session_blocked)
    assert body["code"] == "too_many_login_attempts"
    assert body.keys() == _without_request_id(token_blocked).keys()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_session_login_does_not_reveal_which_names_exist(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    email = await _create_local_user(client, super_admin_token)
    unknown = f"nobody-{uuid4().hex[:8]}@example.com"

    known = await _login(client, SESSION_LOGIN, email, WRONG)
    nobody = await _login(client, SESSION_LOGIN, unknown, WRONG)

    assert known.status_code == nobody.status_code == 401
    assert _without_request_id(known) == _without_request_id(nobody)
