"""The browser session end to end, with PostgreSQL and Redis.

The client talks to http://test.local and httpx does not send Secure cookies
over http, so each request carries the session in an explicit Cookie header.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import jwt
import pytest
import sqlalchemy as sa
from dependency_injector import providers
from fastapi import WebSocketException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.status import WS_1008_POLICY_VIOLATION

from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.authentication import browser_session_service
from eneo.authentication.auth_models import JWTPayload
from eneo.authentication.auth_service import AuthService
from eneo.authentication.browser_session import session_generation
from eneo.authentication.login_attempts import LOGIN_ATTEMPT_LIMIT
from eneo.database.database import SafeAsyncSession, sessionmanager
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.browser_sessions_table import BrowserSessions
from eneo.database.tables.users_table import Users
from eneo.jobs.job_events import job_updates_channel
from eneo.main.config import Settings, get_settings, set_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import AuthenticationException
from eneo.server.dependencies.container import get_user_from_websocket
from eneo.server.websockets import websocket_router
from eneo.users.user import UserState
from tests.integration.test_federation_tenant_admin import (
    SECRET,
    _idp,
    _register,
)
from tests.unit.browser_session_test_utils import expected_set_cookie

PASSWORD = "OriginalPassword1!"
WRONG = "WrongPassword1!"
SESSION = "__Host-eneo_web"
GENERATION = "Eneo-Session-Generation"
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
SESSION_LOGIN = "/api/v1/auth/session/password/"
PROBE = "/api/v1/auth/session/"
TOKEN_LOGIN = "/api/v1/users/login/token/"
FORM = {"Content-Type": "application/x-www-form-urlencoded"}
TICKETS = "/api/v1/module-auth/tickets/"
TICKET = {"module_key": "no-such-module", "redirect_uri": "https://m.example/cb"}
JOB_EVENTS = "/api/v1/jobs/events/"


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


def _claims(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


def _signed(claims: dict) -> str:
    settings = get_settings()
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _rows(user_id: str) -> dict[str, tuple[UUID, UUID, datetime]]:
    async with sessionmanager.session() as session, session.begin():
        rows = await session.execute(
            sa.select(BrowserSessions).where(BrowserSessions.user_id == UUID(user_id))
        )
        return {
            row.sid: (row.user_id, row.tenant_id, row.expires_at)
            for row in rows.scalars()
        }


async def _execute(statement) -> None:
    async with sessionmanager.session() as session, session.begin():
        await session.execute(statement)


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
    # The same user in another browser.
    elsewhere = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))

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
    ticket = await client.post(
        TICKETS, json=TICKET, headers=cookie | SAME_ORIGIN | {GENERATION: generation}
    )
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
    assert stale.json()["eneo_error_code"] == 9090
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

    # The server ended the session: a copy of the cookie made before sign-out
    # no longer works, as the cookie or as Bearer.
    for replay in (cookie | SAME_ORIGIN, _bearer(token)):
        refused = await client.get("/api/v1/users/me/", headers=replay)
        assert refused.status_code == 401, refused.text
        assert GENERATION not in refused.headers
    assert (await client.get(PROBE, headers=cookie | SAME_ORIGIN)).status_code == 401
    # Another session of the same user is not ended.
    other = await client.get(
        "/api/v1/users/me/", headers=SAME_ORIGIN | {"Cookie": f"{SESSION}={elsewhere}"}
    )
    assert other.status_code == 200, other.text

    # A retry, as after a lost response, still clears the cookie.
    retried = await client.post(
        "/api/v1/auth/session/logout/",
        headers=cookie | SAME_ORIGIN | {GENERATION: generation},
    )
    assert retried.status_code == 204
    assert retried.headers.get_list("set-cookie") == cleared


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
    token = _session_token(signed_in)
    cookie = {"Cookie": f"{SESSION}={token}", GENERATION: session_generation(token)}

    me = await client.get("/api/v1/users/me/", headers=cookie | SAME_ORIGIN)
    assert me.status_code == 200, me.text
    assert me.json()["password_status"]["change_required"] is True
    probe = await client.get("/api/v1/auth/session/", headers=cookie | SAME_ORIGIN)
    assert probe.status_code == 204, probe.text
    blocked = await client.post(TICKETS, json=TICKET, headers=cookie | SAME_ORIGIN)
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["eneo_error_code"] == 9070
    # Admitted is not authenticated: a refused request names no generation.
    assert GENERATION not in blocked.headers


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_document_cannot_use_a_replacement_session_from_another_tenant(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    # Each helper creates its own tenant: the ambient cookie now belongs to a
    # different account and organisation from the document's initial session.
    first_email = await _create_local_user(client, super_admin_token)
    second_email = await _create_local_user(client, super_admin_token)
    first = _session_token(await _login(client, SESSION_LOGIN, first_email, PASSWORD))
    second = _session_token(await _login(client, SESSION_LOGIN, second_email, PASSWORD))
    current = SAME_ORIGIN | {"Cookie": f"{SESSION}={second}"}
    stale = current | {GENERATION: session_generation(first)}
    invalidate = "/api/v1/users/me/sessions/invalidate/"

    refused_read = await client.get("/api/v1/users/me/", headers=stale)
    assert refused_read.status_code == 401, refused_read.text
    assert refused_read.json()["eneo_error_code"] == 9090
    assert second_email not in refused_read.text

    for headers in (current, stale):
        refused_write = await client.post(invalidate, headers=headers)
        assert refused_write.status_code == 401, refused_write.text
        assert refused_write.json()["eneo_error_code"] == 9090
        refused_upload = await client.post(
            "/api/v1/groups/00000000-0000-0000-0000-000000000001/info-blobs/upload/",
            files={"file": ("document.txt", b"document", "text/plain")},
            headers=headers,
        )
        assert refused_upload.status_code == 401, refused_upload.text
        assert refused_upload.json()["eneo_error_code"] == 9090

    # Neither rejected write invalidated the replacement account's sessions.
    matching = current | {GENERATION: session_generation(second)}
    still_signed_in = await client.get("/api/v1/users/me/", headers=matching)
    assert still_signed_in.status_code == 200, still_signed_in.text
    assert still_signed_in.json()["email"] == second_email
    accepted_write = await client.post(invalidate, headers=matching)
    assert accepted_write.status_code == 204, accepted_write.text
    assert (await client.get(PROBE, headers=matching)).status_code == 401
    # Credential invalidation of account B never invalidates A.
    first_probe = await client.get(
        PROBE,
        headers=SAME_ORIGIN
        | {"Cookie": f"{SESSION}={first}", GENERATION: session_generation(first)},
    )
    assert first_probe.status_code == 204, first_probe.text


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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_each_browser_sign_in_records_its_own_session(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    email = await _create_local_user(client, super_admin_token)

    first, second = [
        _claims(_session_token(await _login(client, SESSION_LOGIN, email, PASSWORD)))
        for _ in range(2)
    ]
    issued = await _login(client, TOKEN_LOGIN, email, PASSWORD)
    ordinary = _claims(issued.json()["access_token"])

    # The token login keeps its contract; a browser sign-in adds only sid.
    assert "sid" not in ordinary
    for browser in (first, second):
        assert browser.keys() - ordinary.keys() == {"sid"}
        assert browser["auth_method"] == ordinary["auth_method"] == "password"
    assert first["sid"] != second["sid"]
    rows = await _rows(first["user_id"])
    assert rows.keys() == {first["sid"], second["sid"]}
    for browser in (first, second):
        assert rows[browser["sid"]] == (
            UUID(browser["user_id"]),
            UUID(browser["tenant_id"]),
            datetime.fromtimestamp(browser["exp"], timezone.utc),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_session_token_without_its_session_is_refused(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    email = await _create_local_user(client, super_admin_token)
    token = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    other = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    cookie = SAME_ORIGIN | {"Cookie": f"{SESSION}={token}"}
    assert (await client.get("/api/v1/users/me/", headers=cookie)).status_code == 200

    # The setting governs the cookie, not admission: a sid Bearer token is
    # checked against its row with the setting off too.
    set_settings(get_settings().model_copy(update={"browser_session_enabled": False}))
    me = await client.get("/api/v1/users/me/", headers=_bearer(token))
    assert me.status_code == 200, me.text

    await _execute(
        sa.delete(BrowserSessions).where(BrowserSessions.sid == _claims(token)["sid"])
    )
    refused = await client.get("/api/v1/users/me/", headers=_bearer(token))
    assert refused.status_code == 401
    still_in = await client.get("/api/v1/users/me/", headers=_bearer(other))
    assert still_in.status_code == 200

    set_settings(get_settings().model_copy(update={"browser_session_enabled": True}))
    refused = await client.get("/api/v1/users/me/", headers=cookie)
    assert refused.status_code == 401
    assert GENERATION not in refused.headers
    assert (await client.get(PROBE, headers=cookie)).status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sid", [None, "", 7, "not-a-session-id", "a" * 42 + "!"], ids=repr
)
async def test_a_present_sid_must_name_a_session(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
    sid,
):
    # Signed with the real key: only the claim's value is wrong. A null or
    # malformed sid must not read as a token without one.
    email = await _create_local_user(client, super_admin_token)
    token = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    claims = _claims(token)
    claims["sid"] = sid

    refused = await client.get("/api/v1/users/me/", headers=_bearer(_signed(claims)))
    assert refused.status_code == 401
    del claims["sid"]
    ordinary = await client.get("/api/v1/users/me/", headers=_bearer(_signed(claims)))
    assert ordinary.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sign_in_deletes_the_users_expired_sessions(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    email = await _create_local_user(client, super_admin_token)
    other_email = await _create_local_user(client, super_admin_token)
    expired, live = [
        _claims(_session_token(await _login(client, SESSION_LOGIN, email, PASSWORD)))
        for _ in range(2)
    ]
    others = _claims(
        _session_token(await _login(client, SESSION_LOGIN, other_email, PASSWORD))
    )
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    for sid in (expired["sid"], others["sid"]):
        await _execute(
            sa.update(BrowserSessions)
            .where(BrowserSessions.sid == sid)
            .values(expires_at=past)
        )

    latest = await _login(client, SESSION_LOGIN, email, PASSWORD)
    latest_sid = _claims(_session_token(latest))["sid"]

    assert (await _rows(expired["user_id"])).keys() == {live["sid"], latest_sid}
    # Only the signing-in user's rows: another user's go at their next sign-in.
    assert (await _rows(others["user_id"])).keys() == {others["sid"]}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_session_that_cannot_be_recorded_sends_no_cookie(
    app,
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
    monkeypatch,
):
    email = await _create_local_user(client, super_admin_token)
    token = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    taken = _claims(token)
    # The next insert collides with the row above.
    monkeypatch.setattr(
        browser_session_service,
        "secrets",
        SimpleNamespace(token_urlsafe=lambda _: taken["sid"]),
    )

    # The response the server error handler sends, not the raised error.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test.local") as raw:
        refused = await _login(raw, SESSION_LOGIN, email, PASSWORD)

    assert refused.status_code == 500, refused.text
    assert refused.headers.get_list("set-cookie") == []
    assert (await _rows(taken["user_id"])).keys() == {taken["sid"]}


@pytest.fixture
async def federated_callback(
    client,
    super_admin_token,
    fake_idp,
    db_container,
    test_tenant,
):
    """Run one browser SSO sign-in of test@example.com; returns the callback."""
    idp = _idp("browser")
    provider = fake_idp(
        issuer=idp["issuer"],
        client_id="operator-client",
        client_secret=SECRET,
        token_claims={"email": "test@example.com"},
    )
    await _register(
        client,
        super_admin_token,
        test_tenant.id,
        idp,
        canonical_public_origin="https://test.local",
    )
    async with db_container() as container:
        slug = await container.tenant_repo().generate_slug_for_tenant(test_tenant.id)

    async def callback():
        initiated = await client.get(
            "/api/v1/auth/browser/initiate",
            params={"tenant": slug, "next": "/dashboard"},
            headers=SAME_ORIGIN,
        )
        assert initiated.status_code == 303, initiated.text
        location = initiated.headers["location"]
        [state] = parse_qs(urlsplit(location).query)["state"]
        answer = provider.authorize(location)
        [txn] = initiated.headers.get_list("set-cookie")
        return await client.get(
            "/login/callback",
            params={"code": answer.code, "state": state},
            headers={"Cookie": txn.split(";", 1)[0], "Sec-Fetch-Site": "cross-site"},
        )

    return callback


def _session_cookies(response) -> list[str]:
    return [
        cookie
        for cookie in response.headers.get_list("set-cookie")
        if cookie.startswith(f"{SESSION}=")
    ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_federated_browser_sign_in_records_a_session(
    client,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
    federated_callback,
    test_tenant,
):
    async def sign_in() -> dict:
        callback = await federated_callback()
        assert callback.status_code == 303, callback.text
        assert callback.headers["location"] == "/dashboard"
        [session] = _session_cookies(callback)
        token = session.removeprefix(f"{SESSION}=").split(";", 1)[0]
        me = await client.get(
            "/api/v1/users/me/", headers=SAME_ORIGIN | {"Cookie": f"{SESSION}={token}"}
        )
        assert me.status_code == 200, me.text
        return _claims(token)

    first = await sign_in()
    second = await sign_in()

    assert first["sid"] != second["sid"]
    assert first["auth_method"] is None
    rows = await _rows(first["user_id"])
    assert {first["sid"], second["sid"]} <= rows.keys()
    assert rows[first["sid"]][:2] == (UUID(first["user_id"]), test_tenant.id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_federated_session_that_cannot_be_recorded_sends_no_cookie(
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
    federated_callback,
    monkeypatch,
):
    [session] = _session_cookies(await federated_callback())
    taken = _claims(session.removeprefix(f"{SESSION}=").split(";", 1)[0])
    # The next insert collides with the row above.
    monkeypatch.setattr(
        browser_session_service,
        "secrets",
        SimpleNamespace(token_urlsafe=lambda _: taken["sid"]),
    )

    refused = await federated_callback()

    # The sign-in failure page, without a session cookie.
    assert refused.status_code == 303, refused.text
    failure = urlsplit(refused.headers["location"])
    assert failure.path == "/login"
    assert parse_qs(failure.query)["message"] == ["oidc_callback_failed"]
    assert _session_cookies(refused) == []
    assert (await _rows(taken["user_id"])).keys() == {taken["sid"]}


async def _sign_out(client, token: str):
    return await client.post(
        "/api/v1/auth/session/logout/",
        headers=SAME_ORIGIN
        | {"Cookie": f"{SESSION}={token}", GENERATION: session_generation(token)},
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sign_out_clears_a_cookie_that_names_no_session(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    email = await _create_local_user(client, super_admin_token)
    token = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    expired = _signed(_claims(token) | {"exp": 1})

    for dead in (expired, "not-a-token"):
        cleared = await _sign_out(client, dead)
        assert cleared.status_code == 204, cleared.text
        assert cleared.headers.get_list("set-cookie")[0].startswith(f'{SESSION}="";')
    # A token that expired before it was even issued is not trusted to name
    # the session it once had.
    still_in = await client.get(
        "/api/v1/users/me/", headers=SAME_ORIGIN | {"Cookie": f"{SESSION}={token}"}
    )
    assert still_in.status_code == 200, still_in.text


@contextlib.asynccontextmanager
async def _deletion_fails(sid: str) -> AsyncIterator[None]:
    def unavailable(state) -> None:
        if state.is_delete and state.statement.table.name == "browser_sessions":
            raise OperationalError("DELETE", {}, ConnectionError("store unavailable"))

    event.listen(Session, "do_orm_execute", unavailable)
    try:
        yield
    finally:
        event.remove(Session, "do_orm_execute", unavailable)


@contextlib.asynccontextmanager
async def _commit_fails(sid: str) -> AsyncIterator[None]:
    def deleting(connection, cursor, statement, *args) -> None:
        if statement.startswith("DELETE FROM browser_sessions"):
            connection.info["deleted_browser_session"] = True

    def unavailable(connection) -> None:
        if connection.info.pop("deleted_browser_session", False):
            raise OperationalError("COMMIT", {}, ConnectionError("store unavailable"))

    event.listen(Engine, "before_cursor_execute", deleting)
    event.listen(Engine, "commit", unavailable)
    try:
        yield
    finally:
        event.remove(Engine, "before_cursor_execute", deleting)
        event.remove(Engine, "commit", unavailable)


@contextlib.asynccontextmanager
async def _row_locked(sid: str) -> AsyncIterator[None]:
    # Another transaction holds the session's row until the context ends.
    async with sessionmanager.session() as holder, holder.begin():
        await holder.execute(
            sa.select(BrowserSessions.sid)
            .where(BrowserSessions.sid == sid)
            .with_for_update()
        )
        yield


@contextlib.asynccontextmanager
async def _store_stops_answering(sid: str) -> AsyncIterator[None]:
    # The store takes the deletion, then never answers again.
    execute = SafeAsyncSession.execute

    async def stalls(self, statement, *args, **kwargs):
        result = await execute(self, statement, *args, **kwargs)
        if getattr(statement, "is_delete", False):
            await asyncio.Event().wait()
        return result

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(SafeAsyncSession, "execute", stalls)
        yield


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "store_failure",
    [_deletion_fails, _commit_fails, _row_locked, _store_stops_answering],
    ids=["deletion fails", "commit fails", "row locked", "store stops answering"],
)
async def test_sign_out_that_the_store_cannot_confirm_keeps_the_session(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
    monkeypatch,
    store_failure,
):
    deadline = 1.0
    monkeypatch.setattr(browser_session_service, "STORE_DEADLINE_SECONDS", deadline)
    email = await _create_local_user(client, super_admin_token)
    token = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    cookie = SAME_ORIGIN | {"Cookie": f"{SESSION}={token}"}

    async with store_failure(_claims(token)["sid"]):
        async with asyncio.timeout(deadline + 1):
            refused = await _sign_out(client, token)

    # Not signed out: the cookie stays as the handle for a retry.
    assert refused.status_code == 503, refused.text
    assert refused.json()["code"] == "sign_out_unavailable"
    assert refused.headers.get_list("set-cookie") == []
    assert (await client.get("/api/v1/users/me/", headers=cookie)).status_code == 200

    assert (await _sign_out(client, token)).status_code == 204
    assert (await client.get("/api/v1/users/me/", headers=cookie)).status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_signing_in_while_signing_out_keeps_the_new_session(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    email = await _create_local_user(client, super_admin_token)

    for _ in range(5):
        old = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
        signed_out, signed_in = await asyncio.gather(
            _sign_out(client, old), _login(client, SESSION_LOGIN, email, PASSWORD)
        )
        assert signed_out.status_code == 204, signed_out.text
        new = _session_token(signed_in)

        def me(token: str):
            return client.get(
                "/api/v1/users/me/",
                headers=SAME_ORIGIN | {"Cookie": f"{SESSION}={token}"},
            )

        assert (await me(old)).status_code == 401
        assert (await me(new)).status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_browser_session_cannot_open_a_websocket(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    # A socket keeps its user after sign-out; web-next opens none. The token
    # login's Bearer token, which Svelte uses, still opens one.
    email = await _create_local_user(client, super_admin_token)
    session = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    bearer = (await _login(client, TOKEN_LOGIN, email, PASSWORD)).json()["access_token"]
    websocket = SimpleNamespace(scope={"endpoint": websocket_router.connect})

    user = await get_user_from_websocket(
        websocket=websocket, token=bearer, session=None
    )
    assert user.email == email
    with pytest.raises(WebSocketException) as refused:
        await get_user_from_websocket(websocket=websocket, token=session, session=None)
    assert refused.value.code == WS_1008_POLICY_VIOLATION
    still_in = await client.get(
        "/api/v1/users/me/", headers=SAME_ORIGIN | {"Cookie": f"{SESSION}={session}"}
    )
    assert still_in.status_code == 200


async def _subscribers(redis_client, user_id: str, count: int) -> None:
    """Wait until the user's job channel has ``count`` open streams."""
    channel = job_updates_channel(UUID(user_id))
    async with asyncio.timeout(10):
        while dict(await redis_client.pubsub_numsub(channel))[channel.encode()] < count:
            await asyncio.sleep(0.05)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sign_out_ends_an_open_job_event_stream(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
    redis_client,
    monkeypatch,
):
    # The stream authenticates once and stays open; a copy of the cookie that
    # opened it before sign-out must not keep receiving the user's job events.
    monkeypatch.setattr(browser_session_service, "RECHECK_SECONDS", 0.5)
    email = await _create_local_user(client, super_admin_token)
    token = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    bearer = (await _login(client, TOKEN_LOGIN, email, PASSWORD)).json()["access_token"]
    cookie_stream = asyncio.create_task(
        client.get(JOB_EVENTS, headers=SAME_ORIGIN | {"Cookie": f"{SESSION}={token}"})
    )
    bearer_stream = asyncio.create_task(client.get(JOB_EVENTS, headers=_bearer(bearer)))
    try:
        await _subscribers(redis_client, _claims(token)["user_id"], 2)

        assert (await _sign_out(client, token)).status_code == 204
        async with asyncio.timeout(5):
            ended = await cookie_stream
        assert ended.status_code == 200
        # The token login's token has no browser session to end.
        await asyncio.sleep(1)
        assert not bearer_stream.done()
    finally:
        for stream in (cookie_stream, bearer_stream):
            stream.cancel()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "revocation", ["sessions invalidated", "password changed", "account deactivated"]
)
async def test_what_refuses_a_request_ends_an_open_job_event_stream(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
    redis_client,
    monkeypatch,
    revocation,
):
    # None of these deletes the stream's session row; each refuses a new
    # request with its token, and must end the stream it opened as well.
    monkeypatch.setattr(browser_session_service, "RECHECK_SECONDS", 0.5)
    email = await _create_local_user(client, super_admin_token)
    token = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    bearer = (await _login(client, TOKEN_LOGIN, email, PASSWORD)).json()["access_token"]
    cookie = SAME_ORIGIN | {"Cookie": f"{SESSION}={token}"}
    stream = asyncio.create_task(client.get(JOB_EVENTS, headers=cookie))
    try:
        await _subscribers(redis_client, _claims(token)["user_id"], 1)

        if revocation == "sessions invalidated":
            done = await client.post(
                "/api/v1/users/me/sessions/invalidate/", headers=_bearer(bearer)
            )
            assert done.status_code == 204, done.text
        elif revocation == "password changed":
            done = await client.post(
                "/api/v1/users/me/password/",
                json={
                    "current_password": PASSWORD,
                    "new_password": "ReplacedPassword1!",
                },
                headers=_bearer(bearer),
            )
            assert done.status_code == 204, done.text
        else:
            await _execute(
                sa.update(Users)
                .where(Users.email == email)
                .values(state=UserState.INACTIVE.value)
            )

        async with asyncio.timeout(5):
            ended = await stream
        assert ended.status_code == 200
        refused = await client.get("/api/v1/users/me/", headers=cookie)
        assert refused.status_code in (401, 403), refused.text
    finally:
        stream.cancel()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_job_event_stream_ends_when_the_store_cannot_answer_its_check(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
    redis_client,
    monkeypatch,
):
    monkeypatch.setattr(browser_session_service, "RECHECK_SECONDS", 0.5)
    monkeypatch.setattr(browser_session_service, "STORE_DEADLINE_SECONDS", 1.0)
    email = await _create_local_user(client, super_admin_token)
    token = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    stream = asyncio.create_task(
        client.get(JOB_EVENTS, headers=SAME_ORIGIN | {"Cookie": f"{SESSION}={token}"})
    )
    try:
        await _subscribers(redis_client, _claims(token)["user_id"], 1)
        assert sessionmanager._engine is not None
        pool = sessionmanager._engine.pool
        idle = pool.checkedout()
        async with sessionmanager.session() as holder, holder.begin():
            # Every read of the sessions waits behind this transaction.
            await holder.execute(
                sa.text("LOCK TABLE browser_sessions IN ACCESS EXCLUSIVE MODE")
            )
            async with asyncio.timeout(4):
                ended = await stream
            # The check gave its connection back; only the holder's is out.
            assert pool.checkedout() == idle + 1
        assert ended.status_code == 200
    finally:
        stream.cancel()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_job_event_stream_ends_when_its_session_expires(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
    redis_client,
):
    # Between checks too: the stream ends at its token's expiry, which is the
    # session's.
    email = await _create_local_user(client, super_admin_token)
    token = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    soon = int(datetime.now(timezone.utc).timestamp()) + 2
    expiring = _signed(_claims(token) | {"exp": soon})

    async with asyncio.timeout(6):
        ended = await client.get(
            JOB_EVENTS, headers=SAME_ORIGIN | {"Cookie": f"{SESSION}={expiring}"}
        )
    assert ended.status_code == 200
    assert datetime.now(timezone.utc).timestamp() >= soon


EXTEND = "/api/v1/auth/session/extend/"
INVALIDATE = "/api/v1/users/me/sessions/invalidate/"


async def _extension_audit_rows(user_id: str) -> list[dict[str, Any]]:
    async with sessionmanager.session() as session, session.begin():
        rows = await session.scalars(
            sa.select(AuditLog)
            .where(AuditLog.actor_id == user_id)
            .where(AuditLog.action == "session_extended")
        )
        return [
            {"tenant_id": str(row.tenant_id), "metadata": row.log_metadata}
            for row in rows
        ]


@pytest.fixture
async def raw_client(app) -> AsyncIterator[AsyncClient]:
    """A client that receives the 500 instead of the server's exception."""
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test.local",
    ) as client:
        yield client


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_browser_session_extends_itself_and_is_audited(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    email = await _create_local_user(client, super_admin_token)
    token = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    current = SAME_ORIGIN | {
        "Cookie": f"{SESSION}={token}",
        GENERATION: session_generation(token),
    }

    probe = await client.get(PROBE, headers=current)
    assert probe.status_code == 204, probe.text
    assert int(probe.headers["Eneo-Session-Expires-In"]) > 0
    # A fresh session has all of the lifetime it was issued for left.
    assert int(probe.headers["Eneo-Session-Lifetime"]) >= int(
        probe.headers["Eneo-Session-Expires-In"]
    )

    extended = await client.post(EXTEND, headers=current)

    assert extended.status_code == 200, extended.text
    renewed = _session_token(extended)
    assert renewed not in extended.text
    # The page keeps its generation: the renewed cookie names the same one.
    assert (
        extended.json()["generation"]
        == session_generation(renewed)
        == session_generation(token)
    )

    # So a page that never read the answer still acts with the new cookie.
    after = SAME_ORIGIN | {
        "Cookie": f"{SESSION}={renewed}",
        GENERATION: session_generation(token),
    }
    me = await client.get("/api/v1/users/me/", headers=after)
    assert me.status_code == 200, me.text
    assert me.json()["email"] == email
    # Written with the renewal, not queued behind it.
    [row] = await _extension_audit_rows(me.json()["id"])
    assert (
        row["tenant_id"]
        == jwt.decode(token, options={"verify_signature": False})["tenant_id"]
    )
    assert row["metadata"]["success"] is True
    assert token not in repr(row) and renewed not in repr(row)
    # The renewed session is still a password session for the lifecycle gate,
    # and keeps the original sign-in time.
    original = _claims(token)
    claims = _claims(renewed)
    assert claims["auth_method"] == original["auth_method"] == "password"
    assert claims["auth_time"] == original["iat"]
    # It is the same session: no new row, and the row now ends with it.
    assert claims["sid"] == original["sid"]
    assert await _rows(original["user_id"]) == {
        original["sid"]: (
            UUID(original["user_id"]),
            UUID(original["tenant_id"]),
            datetime.fromtimestamp(claims["exp"], timezone.utc),
        )
    }

    # Signing in again, even as the same person, starts another session: the
    # page's generation does not name it.
    again = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    superseded = await client.post(
        "/api/v1/auth/session/logout/", headers=after | {"Cookie": f"{SESSION}={again}"}
    )
    assert superseded.status_code == 401, superseded.text
    assert superseded.json()["eneo_error_code"] == 9090

    # Signing out ends the renewed session, the token it replaced too, and a
    # session that was signed out cannot renew itself.
    signed_out = await client.post("/api/v1/auth/session/logout/", headers=after)
    assert signed_out.status_code == 204, signed_out.text
    for ended in (token, renewed):
        refused = await client.get("/api/v1/users/me/", headers=_bearer(ended))
        assert refused.status_code == 401
    refused = await client.post(EXTEND, headers=after)
    assert refused.status_code == 401, refused.text
    assert refused.headers.get_list("set-cookie") == []
    assert len(await _extension_audit_rows(me.json()["id"])) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_only_a_usable_browser_session_can_extend_itself(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    email = await _create_local_user(client, super_admin_token)
    login = await _login(client, TOKEN_LOGIN, email, PASSWORD)
    bearer = SAME_ORIGIN | {"Authorization": f"Bearer {login.json()['access_token']}"}
    refused_bearer = await client.post(EXTEND, headers=bearer)
    assert refused_bearer.status_code == 401, refused_bearer.text
    assert refused_bearer.headers.get_list("set-cookie") == []

    pending = await _create_local_user(
        client, super_admin_token, must_change_password=True
    )
    token = _session_token(await _login(client, SESSION_LOGIN, pending, PASSWORD))
    cookie = {"Cookie": f"{SESSION}={token}", GENERATION: session_generation(token)}
    blocked = await client.post(EXTEND, headers=cookie | SAME_ORIGIN)
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["eneo_error_code"] == 9070
    assert blocked.headers.get_list("set-cookie") == []

    cross_site = await client.post(
        EXTEND, headers=cookie | {"Sec-Fetch-Site": "cross-site"}
    )
    assert cross_site.status_code == 403
    assert cross_site.headers.get_list("set-cookie") == []

    # Invalidating the account's sessions ends this one too.
    token = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    cookie = SAME_ORIGIN | {
        "Cookie": f"{SESSION}={token}",
        GENERATION: session_generation(token),
    }
    assert (await client.post(INVALIDATE, headers=cookie)).status_code == 204
    invalidated = await client.post(EXTEND, headers=cookie)
    assert invalidated.status_code == 401, invalidated.text
    assert invalidated.headers.get_list("set-cookie") == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_renewal_that_cannot_be_audited_does_not_happen(
    raw_client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
    monkeypatch,
):
    email = await _create_local_user(raw_client, super_admin_token)
    token = _session_token(await _login(raw_client, SESSION_LOGIN, email, PASSWORD))
    current = SAME_ORIGIN | {
        "Cookie": f"{SESSION}={token}",
        GENERATION: session_generation(token),
    }

    async def _fail(self, audit_log):
        raise RuntimeError("audit store down")

    sid = _claims(token)["sid"]
    [before] = (await _rows(_claims(token)["user_id"])).values()

    monkeypatch.setattr(AuditLogRepositoryImpl, "create", _fail)
    refused = await raw_client.post(EXTEND, headers=current)

    # Answered like any store failure, and the page can try again.
    assert refused.status_code == 503
    assert refused.headers.get_list("set-cookie") == []
    # The session's end did not move either.
    assert await _rows(_claims(token)["user_id"]) == {sid: before}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_renewal_the_store_cannot_record_answers_503_and_logs_no_session_id(
    raw_client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
    monkeypatch,
    caplog,
):
    email = await _create_local_user(raw_client, super_admin_token)
    token = _session_token(await _login(raw_client, SESSION_LOGIN, email, PASSWORD))
    sid = _claims(token)["sid"]
    [before] = (await _rows(_claims(token)["user_id"])).values()

    # A store error, as SQLAlchemy raises it, carries the statement's
    # parameters, the session id among them.
    def unavailable(state) -> None:
        if state.is_update and state.statement.table.name == "browser_sessions":
            raise OperationalError(
                "UPDATE browser_sessions", {"sid_1": sid}, TimeoutError("lock timeout")
            )

    event.listen(Session, "do_orm_execute", unavailable)
    root = logging.getLogger()
    root.addHandler(caplog.handler)
    browser_session_service.logger.addHandler(caplog.handler)
    try:
        refused = await raw_client.post(EXTEND, headers=_cookie(token))
    finally:
        event.remove(Session, "do_orm_execute", unavailable)
        root.removeHandler(caplog.handler)
        browser_session_service.logger.removeHandler(caplog.handler)

    assert refused.status_code == 503, refused.text
    assert refused.json()["code"] == "session_extend_unavailable"
    assert refused.headers.get_list("set-cookie") == []
    assert await _rows(_claims(token)["user_id"]) == {sid: before}
    formatted = [logging.Formatter().format(record) for record in caplog.records]
    assert any("browser_session_extend_unavailable" in line for line in formatted)
    assert not any(sid in line or token in line for line in formatted)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_signing_in_again_ends_the_session_the_browser_held(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    email = await _create_local_user(client, super_admin_token)
    first = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    user_id = _claims(first)["user_id"]

    # Signing in again (a session at its maximum age offers it) replaces the
    # browser's session: the one its cookie named ends, and is not left behind.
    again = await client.post(
        SESSION_LOGIN,
        data={"username": email, "password": PASSWORD},
        headers=FORM | SAME_ORIGIN | {"Cookie": f"{SESSION}={first}"},
    )
    second = _session_token(again)
    assert (await _rows(user_id)).keys() == {_claims(second)["sid"]}
    me = await client.get("/api/v1/users/me/", headers=_cookie(first))
    assert me.status_code == 401
    assert (
        await client.get("/api/v1/users/me/", headers=_cookie(second))
    ).status_code == 200

    # A sign-in that fails ends nothing: the browser keeps its session.
    failed = await client.post(
        SESSION_LOGIN,
        data={"username": email, "password": "not-the-password"},
        headers=FORM | SAME_ORIGIN | {"Cookie": f"{SESSION}={second}"},
    )
    assert failed.status_code == 401, failed.text
    assert (await _rows(user_id)).keys() == {_claims(second)["sid"]}

    # A cookie that names no session of its own (forged) ends nothing.
    forged = jwt.encode(
        _claims(second), "x" * 64, algorithm=get_settings().jwt_algorithm
    )
    third = _session_token(
        await client.post(
            SESSION_LOGIN,
            data={"username": email, "password": PASSWORD},
            headers=FORM | SAME_ORIGIN | {"Cookie": f"{SESSION}={forged}"},
        )
    )
    assert (await _rows(user_id)).keys() == {
        _claims(second)["sid"],
        _claims(third)["sid"],
    }


def _cookie(token: str) -> dict[str, str]:
    return SAME_ORIGIN | {
        "Cookie": f"{SESSION}={token}",
        GENERATION: session_generation(token),
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_signing_out_with_the_token_a_renewal_replaced_ends_the_session(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    # A renewal keeps the sid, so a sign-out sent with the token it replaced,
    # which expires on the way, must still end the renewed session.
    email = await _create_local_user(client, super_admin_token)
    claims = _claims(
        _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    )
    bearer = (await _login(client, TOKEN_LOGIN, email, PASSWORD)).json()["access_token"]
    now = int(time.time())
    # A short session: its token and its row end two seconds from now.
    original = _signed(claims | {"iat": now - 60, "exp": now + 2})
    await _execute(
        sa.update(BrowserSessions)
        .where(BrowserSessions.sid == claims["sid"])
        .values(expires_at=datetime.fromtimestamp(now + 2, timezone.utc))
    )
    extended = await client.post(EXTEND, headers=_cookie(original))
    assert extended.status_code == 200, extended.text
    renewed = _session_token(extended)
    expired_bearer = _signed(_claims(bearer) | {"iat": now - 60, "exp": now + 2})
    await asyncio.sleep(now + 2 - time.time() + 0.2)

    # Only sign-out takes an expired token: authentication, renewal and a
    # WebSocket still refuse one.
    for refused in (_cookie(original), _bearer(original)):
        me = await client.get("/api/v1/users/me/", headers=refused)
        assert me.status_code == 401, me.text
    not_renewed = await client.post(EXTEND, headers=_cookie(original))
    assert not_renewed.status_code == 401, not_renewed.text
    assert not_renewed.headers.get_list("set-cookie") == []
    websocket = SimpleNamespace(scope={"endpoint": websocket_router.connect})
    with pytest.raises(WebSocketException):
        await get_user_from_websocket(
            websocket=websocket, token=expired_bearer, session=None
        )
    assert (
        await client.get("/api/v1/users/me/", headers=_cookie(renewed))
    ).status_code == 200

    signed_out = await _sign_out(client, original)

    assert signed_out.status_code == 204, signed_out.text
    me = await client.get("/api/v1/users/me/", headers=_cookie(renewed))
    assert me.status_code == 401, me.text
    assert await _rows(claims["user_id"]) == {}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_only_a_genuine_recently_expired_token_signs_its_session_out(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
    monkeypatch,
    caplog,
):
    email = await _create_local_user(client, super_admin_token)
    token = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    claims = _claims(token)
    now = int(time.time())
    # Issued a minute ago, expired a second ago.
    recent = claims | {"iat": now - 61, "exp": now - 1}
    refused = {
        "forged": jwt.encode(recent, "x" * 64, algorithm=get_settings().jwt_algorithm),
        "unsigned": jwt.encode(recent, None, algorithm="none"),
        "another audience": _signed(recent | {"aud": "another-audience"}),
        "another issuer": _signed(recent | {"iss": "https://another.example"}),
        "untyped": _signed(recent | {"credential_version": "0"}),
        "without a session": _signed(
            {name: value for name, value in recent.items() if name != "sid"}
        ),
        "another user's": _signed(recent | {"user_id": str(uuid4())}),
        # Expired longer ago than it was valid for.
        "expired too long ago": _signed(claims | {"iat": now - 121, "exp": now - 61}),
    }

    for name, dead in refused.items():
        signed_out = await _sign_out(client, dead)
        assert signed_out.status_code == 204, (name, signed_out.text)
        assert (await _rows(claims["user_id"])).keys() == {claims["sid"]}, name
    me = await client.get("/api/v1/users/me/", headers=_cookie(token))
    assert me.status_code == 200, me.text

    # The genuine token ends it; a failure to do so is logged without it.
    genuine = _signed(recent)
    monkeypatch.setattr(browser_session_service, "STORE_DEADLINE_SECONDS", 1.0)
    browser_session_service.logger.addHandler(caplog.handler)
    try:
        async with _deletion_fails(claims["sid"]):
            unavailable = await _sign_out(client, genuine)
    finally:
        browser_session_service.logger.removeHandler(caplog.handler)
    assert unavailable.status_code == 503, unavailable.text
    assert caplog.records
    assert not any(genuine in repr(vars(record)) for record in caplog.records)

    assert (await _sign_out(client, genuine)).status_code == 204
    assert await _rows(claims["user_id"]) == {}
    me = await client.get("/api/v1/users/me/", headers=_cookie(token))
    assert me.status_code == 401, me.text


def _payload(token: str) -> JWTPayload:
    settings = get_settings()
    return AuthService().get_jwt_payload(
        token,
        key=str(settings.jwt_secret),
        aud=settings.jwt_audience,
        algs=[settings.jwt_algorithm],
    )


async def _issue(current: JWTPayload, seconds: float) -> str:
    """A token for the session's user, as a renewal issues it."""
    async with sessionmanager.session() as session, session.begin():
        container = Container(session=providers.Object(session))
        user = await container.user_repo().get_user_by_id_and_tenant_id(
            current.user_id, tenant_id=current.tenant_id
        )
        return AuthService().create_access_token_for_user(user, expires_in=seconds / 60)


async def _renew(current: JWTPayload, issued: str) -> str:
    """BrowserSessionService.renew in a database session of its own."""
    async with sessionmanager.session() as session:
        container = Container(session=providers.Object(session))
        async with session.begin():
            user = await container.user_repo().get_user_by_id_and_tenant_id(
                current.user_id, tenant_id=current.tenant_id
            )
        return await container.browser_session_service().renew(current, issued, user)


async def _renewal_waits_for_the_row() -> None:
    async with asyncio.timeout(5):
        while True:
            async with sessionmanager.session() as session, session.begin():
                if await session.scalar(
                    sa.text(
                        "SELECT count(*) FROM pg_stat_activity"
                        " WHERE wait_event_type = 'Lock'"
                        " AND query LIKE 'UPDATE browser_sessions%'"
                    )
                ):
                    return
            await asyncio.sleep(0.05)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_renewal_issued_earlier_but_recorded_later_keeps_the_later_end(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
    monkeypatch,
):
    email = await _create_local_user(client, super_admin_token)
    token = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    current = _payload(token)
    # The session ends in a minute; both renewals move that end.
    await _execute(
        sa.update(BrowserSessions)
        .where(BrowserSessions.sid == current.sid)
        .values(expires_at=datetime.now(timezone.utc) + timedelta(minutes=1))
    )
    # Issued first, so it ends first.
    earlier = await _issue(current, 3)
    later = await _issue(current, 120)

    # The later renewal updates the row and holds it, uncommitted, in its
    # audit write; the earlier one waits for the row, then updates it last.
    create = AuditLogRepositoryImpl.create
    held, release = asyncio.Event(), asyncio.Event()

    async def hold_the_first(self, audit_log):
        created = await create(self, audit_log)
        if not held.is_set():
            held.set()
            await release.wait()
        return created

    monkeypatch.setattr(AuditLogRepositoryImpl, "create", hold_the_first)
    later_renewal = asyncio.create_task(_renew(current, later))
    earlier_renewal: asyncio.Task | None = None
    try:
        # A renewal that fails before its audit write must fail the test, not hang it.
        held_or_failed = asyncio.create_task(held.wait())
        async with asyncio.timeout(30):
            await asyncio.wait(
                {held_or_failed, later_renewal}, return_when=asyncio.FIRST_COMPLETED
            )
        held_or_failed.cancel()
        if later_renewal.done():
            later_renewal.result()
        earlier_renewal = asyncio.create_task(_renew(current, earlier))
        async with asyncio.timeout(30):
            await _renewal_waits_for_the_row()
    finally:
        release.set()
    async with asyncio.timeout(30):
        renewed_later = await later_renewal
        renewed_earlier = await earlier_renewal

    ends = _claims(renewed_earlier)["exp"], _claims(renewed_later)["exp"]
    assert ends[0] < ends[1]
    [(_, _, expires_at)] = (await _rows(str(current.user_id))).values()
    assert expires_at == datetime.fromtimestamp(ends[1], timezone.utc)
    # Between the two ends, the later token still authenticates.
    await asyncio.sleep(ends[0] - time.time() + 0.2)
    me = await client.get("/api/v1/users/me/", headers=_cookie(renewed_later))
    assert me.status_code == 200, me.text
    me = await client.get("/api/v1/users/me/", headers=_cookie(renewed_earlier))
    assert me.status_code == 401, me.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_renewal_after_sign_out_does_not_bring_the_session_back(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    # A renewal admitted before a sign-out that deletes the row first.
    email = await _create_local_user(client, super_admin_token)
    token = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    current = _payload(token)
    issued = await _issue(current, 120)

    assert (await _sign_out(client, token)).status_code == 204

    with pytest.raises(AuthenticationException):
        await _renew(current, issued)
    assert await _rows(str(current.user_id)) == {}
    assert await _extension_audit_rows(str(current.user_id)) == []
