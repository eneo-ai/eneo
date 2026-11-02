"""The browser session end to end, with PostgreSQL and Redis.

The client talks to http://test.local and httpx does not send Secure cookies
over http, so each request carries the session in an explicit Cookie header.
"""

import asyncio
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import jwt
import pytest
import sqlalchemy as sa
from fastapi import WebSocketException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.status import WS_1008_POLICY_VIOLATION

from eneo.authentication import browser_session_service
from eneo.authentication.auth_service import AuthService
from eneo.authentication.browser_session import session_generation
from eneo.authentication.login_attempts import LOGIN_ATTEMPT_LIMIT
from eneo.database.database import sessionmanager
from eneo.database.tables.browser_sessions_table import BrowserSessions
from eneo.main.config import Settings, get_settings, set_settings
from eneo.server.dependencies.container import get_user_from_websocket
from eneo.server.websockets import websocket_router
from tests.integration.test_federation_tenant_admin import (
    _discovery,
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_federated_browser_sign_in_records_a_session(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
    oidc_mock,
    jwks_mock,
    db_container,
    test_tenant,
    monkeypatch,
):
    idp = _idp("browser")
    oidc_mock(
        discovery=_discovery(idp),
        tokens={
            (idp["token_endpoint"], code): {"id_token": "id", "access_token": "at"}
            for code in ("code-1", "code-2")
        },
    )
    jwks_mock()
    monkeypatch.setattr(
        AuthService,
        "get_payload_from_openid_jwt",
        lambda self, **kwargs: {"email": "test@example.com", "email_verified": True},
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

    async def sign_in(code: str) -> dict:
        initiated = await client.get(
            "/api/v1/auth/browser/initiate",
            params={"tenant": slug, "next": "/dashboard"},
            headers=SAME_ORIGIN,
        )
        assert initiated.status_code == 303, initiated.text
        [state] = parse_qs(urlsplit(initiated.headers["location"]).query)["state"]
        [txn] = initiated.headers.get_list("set-cookie")
        callback = await client.get(
            "/login/callback",
            params={"code": code, "state": state},
            headers={"Cookie": txn.split(";", 1)[0], "Sec-Fetch-Site": "cross-site"},
        )
        assert callback.status_code == 303, callback.text
        assert callback.headers["location"] == "/dashboard"
        [session] = [
            cookie
            for cookie in callback.headers.get_list("set-cookie")
            if cookie.startswith(f"{SESSION}=")
        ]
        token = session.removeprefix(f"{SESSION}=").split(";", 1)[0]
        me = await client.get(
            "/api/v1/users/me/", headers=SAME_ORIGIN | {"Cookie": f"{SESSION}={token}"}
        )
        assert me.status_code == 200, me.text
        return _claims(token)

    first = await sign_in("code-1")
    second = await sign_in("code-2")

    assert first["sid"] != second["sid"]
    assert first["auth_method"] is None
    rows = await _rows(first["user_id"])
    assert {first["sid"], second["sid"]} <= rows.keys()
    assert rows[first["sid"]][:2] == (UUID(first["user_id"]), test_tenant.id)


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
    # An expired token is not trusted to name the session it once had.
    still_in = await client.get(
        "/api/v1/users/me/", headers=SAME_ORIGIN | {"Cookie": f"{SESSION}={token}"}
    )
    assert still_in.status_code == 200, still_in.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sign_out_that_cannot_reach_the_store_keeps_the_session(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
    browser_session_on,
):
    email = await _create_local_user(client, super_admin_token)
    token = _session_token(await _login(client, SESSION_LOGIN, email, PASSWORD))
    cookie = SAME_ORIGIN | {"Cookie": f"{SESSION}={token}"}

    def unavailable(state) -> None:
        if state.is_delete and state.statement.table.name == "browser_sessions":
            raise OperationalError("DELETE", {}, ConnectionError("store unavailable"))

    event.listen(Session, "do_orm_execute", unavailable)
    try:
        refused = await _sign_out(client, token)
    finally:
        event.remove(Session, "do_orm_execute", unavailable)

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
