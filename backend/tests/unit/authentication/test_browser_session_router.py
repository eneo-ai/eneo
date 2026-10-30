"""The browser session endpoints: password sign-in, sign-out and the probe.

Sign-in sets the session cookie and answers 204 with an empty body; its
errors are exactly those of ``/users/login/token/``. Both run the Sec-Fetch-Site
gate first. Sign-out clears the cookies, but not a session the page did not
expect. The probe names the generation of the cookie session it admitted.
"""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient
from freezegun import freeze_time
from httpx import Response
from starlette.requests import Request

from eneo.authentication import browser_session
from eneo.authentication.api_key_v2_repo import ApiKeysV2Repository
from eneo.authentication.auth_models import AccessToken
from eneo.authentication.auth_service import AuthService
from eneo.authentication.browser_session import session_generation
from eneo.authentication.browser_session_router import (
    create_browser_session,
    end_browser_session,
    get_browser_session,
)
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    access_for,
)
from eneo.authentication.login_attempts import LoginAttempt
from eneo.database.database import (
    AsyncSession,
    get_session,
    get_session_with_transaction,
)
from eneo.info_blobs.info_blob_repo import InfoBlobRepository
from eneo.main.config import Settings, get_settings, set_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import (
    AuthenticationException,
    ErrorCodes,
    TenantSuspendedException,
    UserInactiveException,
)
from eneo.main.logging import OTELJSONFormatter
from eneo.server.endpoint_routes import endpoint_routes
from eneo.server.main import get_application
from eneo.tenants.tenant import TenantState
from eneo.users import user_router
from eneo.users.user import UserInDB, UserState
from eneo.users.user_service import UserService
from tests.fixtures import TEST_USER
from tests.unit.browser_session_test_utils import expected_set_cookie
from tests.unit.test_endpoint_access import make_user

SESSION_LOGIN = "/api/v1/auth/session/password/"
TOKEN_LOGIN = "/api/v1/users/login/token/"
LOGOUT = "/api/v1/auth/session/logout/"
PROBE = "/api/v1/auth/session/"
ME = "/api/v1/users/me/"
ADMIN_ONLY = "/api/v1/admin/password-policy"
SESSION = "__Host-eneo_web"
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
GENERATION = "Eneo-Session-Generation"
EMAIL = "browser@example.com"
PASSWORD = "BrowserSession-SENTINEL-1!"
FORM = {"username": EMAIL, "password": PASSWORD}
NOW = "2026-10-28 12:00:00"
REFUSING_SITES = [{}, {"Sec-Fetch-Site": "cross-site"}]
REFUSING_SITES += [{"Sec-Fetch-Site": "same-site"}, {"Sec-Fetch-Site": "none"}]
NEXT_ERA = ("eneo_session", "eneo_oidc_txn", "eneo_federation_txn")
# SimpleCookie renders an empty value as a quoted empty string.
EMPTY = '""'


@pytest.fixture(autouse=True)
def browser_settings() -> Iterator[Settings]:
    original = get_settings()
    settings = original.model_copy(
        update={"browser_session_enabled": True, "environment": "production"}
    )
    set_settings(settings)
    yield settings
    set_settings(original)


def mint(minutes: float = 15) -> str:
    return AuthService().create_access_token_for_user(TEST_USER, expires_in=minutes)


@dataclass
class Endpoints:
    client: TestClient
    login: AsyncMock
    count: AsyncMock
    user: UserInDB
    valid_tokens: set[str]


@pytest.fixture
def endpoints(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> Iterator[Endpoints]:
    """The real app. Password login stops at UserService.login and the attempt
    counter; canonical authentication stops at the token lookup."""
    service = AsyncMock(spec=UserService)
    count = AsyncMock(return_value=LoginAttempt(True, 4, 600))
    monkeypatch.setattr(user_router, "count_login_attempt", count)
    monkeypatch.setattr(user_router, "clear_login_attempts", AsyncMock())
    login_container = Container(
        user_service=providers.Object(service),
        redis_client=providers.Object(object()),
    )

    user = make_user()
    valid_tokens: set[str] = set()

    async def user_from_token(_self: UserService, token: str) -> UserInDB:
        if token not in valid_tokens:
            raise AuthenticationException("Invalid token")
        return user

    monkeypatch.setattr(UserService, "_get_user_from_token", user_from_token)
    monkeypatch.setattr(
        ApiKeysV2Repository,
        "get_latest_active_by_owner",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        InfoBlobRepository, "get_total_size_of_user", AsyncMock(return_value=0)
    )

    async def session() -> AsyncSession:
        database = AsyncMock(spec=AsyncSession)
        database.in_transaction.return_value = True
        return database

    app = get_application()
    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_session_with_transaction] = session
    for route in endpoint_routes(app.routes):
        if route.path in (SESSION_LOGIN, TOKEN_LOGIN):
            assert route.dependant is not None
            [container] = [
                dependency
                for dependency in route.dependant.dependencies
                if dependency.name == "container"
            ]
            app.dependency_overrides[container.call] = lambda: login_container

    caplog.set_level(logging.DEBUG)
    # eneo.main.logging may have raised an ancestor to CRITICAL at import.
    caplog.set_level(logging.DEBUG, logger="eneo.server.exception_handlers")
    # The app's logging setup replaced the root handlers, and SimpleLogger does
    # not propagate: capture the root and both SimpleLoggers directly.
    loggers = (logging.getLogger(), user_router.logger, browser_session.logger)
    for logger in loggers:
        logger.addHandler(caplog.handler)
    client = TestClient(app, client=("10.0.0.1", 50000))
    try:
        yield Endpoints(client, service.login, count, user, valid_tokens)
    finally:
        client.close()
        for logger in loggers:
            logger.removeHandler(caplog.handler)


def all_logs(caplog: pytest.LogCaptureFixture) -> str:
    formatter = OTELJSONFormatter()
    return "\n".join(formatter.format(record) for record in caplog.records)


def set_cookies(response: Response) -> list[str]:
    return response.headers.get_list("set-cookie")


def test_session_endpoints_are_declared():
    for endpoint in (create_browser_session, end_browser_session):
        policy = access_for(endpoint)
        assert policy is not None
        assert policy.authentication is Authentication.PUBLIC
        assert policy.authorization is Authorization.PUBLIC

    probe = access_for(get_browser_session)
    assert probe is not None
    assert probe.authentication is Authentication.SESSION
    assert probe.authorization is Authorization.AUTHENTICATED
    # A session that must replace its password can still be probed.
    assert probe.reachable_before_password_change


def test_password_session_sets_cookie_without_token_in_body(
    endpoints: Endpoints, caplog: pytest.LogCaptureFixture
):
    with freeze_time(NOW):
        token = mint(15)
        endpoints.login.return_value = AccessToken(
            access_token=token, token_type="bearer"
        )

        response = endpoints.client.post(SESSION_LOGIN, data=FORM, headers=SAME_ORIGIN)

    assert response.status_code == 204
    assert response.content == b""
    assert set_cookies(response) == [
        expected_set_cookie(SESSION, token, 15 * 60, production=True)
    ]
    assert response.headers["cache-control"] == "no-store"
    # Sign-in ends the document that sent it; no page adopts its generation.
    assert GENERATION not in response.headers
    endpoints.login.assert_awaited_once()
    assert endpoints.login.await_args is not None
    assert endpoints.login.await_args.args[:2] == (EMAIL, PASSWORD)
    assert token not in all_logs(caplog)
    assert PASSWORD not in all_logs(caplog)


def test_password_session_replaces_a_planted_session(endpoints: Endpoints):
    planted = mint()
    issued = mint(30)
    endpoints.login.return_value = AccessToken(access_token=issued, token_type="bearer")

    response = endpoints.client.post(
        SESSION_LOGIN,
        data=FORM,
        headers=SAME_ORIGIN | {"Cookie": f"{SESSION}={planted}"},
    )

    assert response.status_code == 204
    [cookie] = set_cookies(response)
    assert cookie.startswith(f"{SESSION}={issued};")
    assert planted not in cookie


@pytest.mark.parametrize(
    ("case", "status"), [("cross-site", 403), ("disabled", 404), ("same-origin", 400)]
)
def test_password_session_guards_run_before_the_body_is_read(
    endpoints: Endpoints,
    browser_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    status: int,
):
    # FastAPI reads a form body before it solves any dependency; a refused
    # request must not get that far (a malformed body would answer 400 first,
    # a multipart file part would be spooled to disk).
    parsed: list[str] = []
    original_form = Request.form

    def form(request: Request, *args: object, **kwargs: object):
        parsed.append(request.url.path)
        return original_form(request, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Request, "form", form)
    if case == "disabled":
        set_settings(
            browser_settings.model_copy(update={"browser_session_enabled": False})
        )
    site = {"Sec-Fetch-Site": "cross-site" if case == "cross-site" else "same-origin"}

    response = endpoints.client.post(
        SESSION_LOGIN,
        content=b"--x\r\n",
        headers=site | {"Content-Type": "multipart/form-data"},
    )

    assert response.status_code == status
    assert parsed == ([SESSION_LOGIN] if case == "same-origin" else [])
    endpoints.login.assert_not_awaited()


@pytest.mark.parametrize("site", REFUSING_SITES)
def test_password_session_refuses_without_same_origin(
    endpoints: Endpoints, caplog: pytest.LogCaptureFixture, site: dict[str, str]
):
    response = endpoints.client.post(SESSION_LOGIN, data=FORM, headers=site)

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "browser_origin_refused"
    # The login form shows 9019 and 9025 as a deactivated account.
    assert body["eneo_error_code"] not in (
        ErrorCodes.USER_INACTIVE.value,
        ErrorCodes.TENANT_SUSPENDED.value,
    )
    assert set_cookies(response) == []
    endpoints.login.assert_not_awaited()
    endpoints.count.assert_not_awaited()
    [record] = [r for r in caplog.records if r.getMessage() == "browser_origin_refused"]
    assert getattr(record, "method") == "POST"
    assert getattr(record, "path") == SESSION_LOGIN


def _contract(response: Response) -> tuple[int, object, dict[str, str]]:
    body = response.json()
    if isinstance(body, dict):
        body.pop("request_id", None)
        if response.status_code == 500:
            error_id = body.pop("error_id")
            assert isinstance(error_id, str) and len(error_id) == 8
            assert all(char in "0123456789abcdef" for char in error_id)
    volatile = {"x-correlation-id", "x-trace-id", "date", "content-length"}
    headers = {k: v for k, v in response.headers.items() if k not in volatile}
    return response.status_code, body, headers


@pytest.mark.parametrize(
    ("attempt", "login_error", "form"),
    [
        (LoginAttempt(True, 3, 600), AuthenticationException("no"), FORM),
        (LoginAttempt(True, 0, 600), AuthenticationException("no"), FORM),
        (LoginAttempt(False, 0, 321), None, FORM),
        (LoginAttempt(True, 4, 600), UserInactiveException(), FORM),
        (LoginAttempt(True, 4, 600), TenantSuspendedException(), FORM),
        (LoginAttempt(True, 4, 600), RuntimeError("boom"), FORM),
        (None, None, {"password": PASSWORD}),
        (None, None, {"username": EMAIL}),
        (None, None, {}),
        (None, None, {"username": "not-an-email", "password": PASSWORD}),
    ],
    ids=[
        "401",
        "401-last",
        "429",
        "403-inactive",
        "403-suspended",
        "500",
        "422-username",
        "422-password",
        "422-both",
        "422-email",
    ],
)
def test_password_session_keeps_login_error_contract(
    endpoints: Endpoints,
    caplog: pytest.LogCaptureFixture,
    attempt: LoginAttempt | None,
    login_error: Exception | None,
    form: dict[str, str],
):
    if attempt is not None:
        endpoints.count.return_value = attempt
    endpoints.login.side_effect = login_error

    token_response = endpoints.client.post(TOKEN_LOGIN, data=form, headers=SAME_ORIGIN)
    session_response = endpoints.client.post(
        SESSION_LOGIN, data=form, headers=SAME_ORIGIN
    )

    assert token_response.status_code >= 400
    assert _contract(session_response) == _contract(token_response)
    assert session_response.headers["x-correlation-id"]
    assert set_cookies(session_response) == []
    if session_response.status_code == 429:
        assert session_response.headers["retry-after"] == "321"
    if session_response.status_code == 422:
        locations = [error["loc"] for error in session_response.json()["detail"]]
        assert all(location[0] == "body" for location in locations)
        assert {location[1] for location in locations} <= {"username", "password"}
    assert PASSWORD not in session_response.text
    assert PASSWORD not in all_logs(caplog)


@pytest.mark.parametrize(
    ("environment", "session", "txn", "production"),
    [
        ("production", SESSION, "__Host-eneo_oidc_txn", True),
        ("development", "eneo_web", "eneo_web_txn", False),
    ],
)
def test_logout_clears_session_txn_and_next_era_cookies(
    endpoints: Endpoints,
    browser_settings: Settings,
    environment: str,
    session: str,
    txn: str,
    production: bool,
):
    set_settings(browser_settings.model_copy(update={"environment": environment}))
    token = mint()

    response = endpoints.client.post(
        LOGOUT,
        headers=SAME_ORIGIN
        | {"Cookie": f"{session}={token}", GENERATION: session_generation(token)},
    )

    assert response.status_code == 204
    assert response.content == b""
    assert set_cookies(response) == [
        expected_set_cookie(name, EMPTY, 0, production=production)
        for name in (session, txn, *NEXT_ERA)
    ]


@pytest.mark.parametrize("site", REFUSING_SITES)
def test_logout_refuses_cross_site(endpoints: Endpoints, site: dict[str, str]):
    response = endpoints.client.post(
        LOGOUT, headers=site | {"Cookie": f"{SESSION}={mint()}"}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "browser_origin_refused"
    assert set_cookies(response) == []


@pytest.mark.parametrize("expected", [None, "stale"])
def test_logout_keeps_a_session_the_page_did_not_expect(
    endpoints: Endpoints, caplog: pytest.LogCaptureFixture, expected: str | None
):
    # The page loaded under one session; another tab has since signed in.
    page_session, current = mint(), mint(30)

    headers = SAME_ORIGIN | {"Cookie": f"{SESSION}={current}"}
    if expected is not None:
        headers[GENERATION] = session_generation(page_session)
    response = endpoints.client.post(LOGOUT, headers=headers)

    assert response.status_code == 401
    body = response.json()
    assert (
        body["eneo_error_code"] == ErrorCodes.SESSION_GENERATION_MISMATCH.value == 9090
    )
    assert body["code"] == "session_generation_mismatch"
    assert body["message"] == "The browser session changed after this page was loaded."
    assert set_cookies(response) == []
    # Logged once, by the shared domain-exception handler.
    assert [
        (r.name, r.levelno) for r in caplog.records if r.name.startswith("eneo.")
    ] == [("eneo.server.exception_handlers", logging.WARNING)]
    assert current not in all_logs(caplog)


@pytest.mark.parametrize("case", ["expected generation", "no session", "dead session"])
def test_logout_clears_what_the_page_expects_or_cannot_use(
    endpoints: Endpoints, case: str
):
    token = "not-a-token" if case == "dead session" else mint()
    headers = dict(SAME_ORIGIN)
    if case != "no session":
        headers["Cookie"] = f"{SESSION}={token}"
    headers[GENERATION] = session_generation(token)

    response = endpoints.client.post(LOGOUT, headers=headers)

    # Sign-out never needs a usable session, so a dead one can be cleared.
    assert response.status_code == 204
    assert set_cookies(response)[0] == expected_set_cookie(
        SESSION, EMPTY, 0, production=True
    )


@pytest.mark.parametrize("path", [SESSION_LOGIN, LOGOUT, PROBE])
def test_disabled_setting_returns_404(
    endpoints: Endpoints, browser_settings: Settings, path: str
):
    set_settings(browser_settings.model_copy(update={"browser_session_enabled": False}))
    token = mint()
    endpoints.valid_tokens.add(token)
    headers = SAME_ORIGIN | {"Cookie": f"{SESSION}={token}"}

    if path == PROBE:
        response = endpoints.client.get(path, headers=headers)
    else:
        response = endpoints.client.post(path, data=FORM, headers=headers)

    assert response.status_code == 404
    assert set_cookies(response) == []
    assert GENERATION not in response.headers
    endpoints.login.assert_not_awaited()


def test_probe_names_the_admitted_cookie_session(endpoints: Endpoints):
    token = mint()
    endpoints.valid_tokens.add(token)

    response = endpoints.client.get(
        PROBE, headers=SAME_ORIGIN | {"Cookie": f"{SESSION}={token}"}
    )

    assert response.status_code == 204
    assert response.headers[GENERATION] == session_generation(token)
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("restricted", ["dead cookie", "suspended tenant"])
def test_probe_identifies_a_rejected_cookie_only_for_guarded_logout(
    endpoints: Endpoints, restricted: str
):
    token = mint()
    if restricted == "suspended tenant":
        endpoints.valid_tokens.add(token)
        endpoints.user.tenant.state = TenantState.SUSPENDED
    headers = SAME_ORIGIN | {"Cookie": f"{SESSION}={token}"}
    probe = endpoints.client.get(PROBE, headers=headers)
    assert probe.status_code == (403 if restricted == "suspended tenant" else 401)
    assert probe.headers[GENERATION] == session_generation(token)
    assert probe.headers["cache-control"] == "no-store"

    signed_out = endpoints.client.post(
        LOGOUT, headers=headers | {GENERATION: probe.headers[GENERATION]}
    )
    assert signed_out.status_code == 204
    assert set_cookies(signed_out)

    replacement = mint(30)
    refused = endpoints.client.post(
        LOGOUT,
        headers=SAME_ORIGIN
        | {"Cookie": f"{SESSION}={replacement}", GENERATION: probe.headers[GENERATION]},
    )
    assert refused.status_code == 401
    assert refused.json()["eneo_error_code"] == 9090
    assert set_cookies(refused) == []


def test_stale_probe_never_exposes_the_replacement_cookie_generation(
    endpoints: Endpoints,
):
    replacement = mint(30)
    endpoints.valid_tokens.add(replacement)
    response = endpoints.client.get(
        PROBE,
        headers=SAME_ORIGIN
        | {
            "Cookie": f"{SESSION}={replacement}",
            GENERATION: session_generation(mint()),
        },
    )
    assert response.status_code == 401
    assert response.json()["eneo_error_code"] == 9090
    assert GENERATION not in response.headers
    assert set_cookies(response) == []


@pytest.mark.parametrize(
    "case", ["bearer token", "dead cookie", "cross-site cookie", "no credential"]
)
def test_probe_refuses_without_an_admitted_cookie_session(
    endpoints: Endpoints, case: str
):
    token = mint()
    endpoints.valid_tokens.add(token)
    headers = {
        "bearer token": SAME_ORIGIN | {"Authorization": f"Bearer {token}"},
        "dead cookie": SAME_ORIGIN | {"Cookie": f"{SESSION}=not-a-token"},
        "cross-site cookie": {
            "Sec-Fetch-Site": "cross-site",
            "Cookie": f"{SESSION}={token}",
        },
        "no credential": SAME_ORIGIN,
    }[case]

    response = endpoints.client.get(PROBE, headers=headers)

    assert response.status_code == 401
    if case == "dead cookie":
        assert response.headers[GENERATION] == session_generation("not-a-token")
    else:
        assert GENERATION not in response.headers


@pytest.mark.parametrize("refusal", ["missing permission", "inactive user"])
def test_a_refused_cookie_session_names_no_generation(
    endpoints: Endpoints, refusal: str
):
    # Ordinary API refusals never name an admitted generation, including when
    # the user is inactive. Only the bootstrap probe has the logout exception.
    token = mint()
    endpoints.valid_tokens.add(token)
    path = ADMIN_ONLY
    if refusal == "inactive user":
        endpoints.user.state = UserState.INACTIVE

    response = endpoints.client.get(
        path, headers=SAME_ORIGIN | {"Cookie": f"{SESSION}={token}"}
    )

    assert response.status_code == 403, response.text
    assert GENERATION not in response.headers


def test_cookie_authenticated_responses_name_their_generation(endpoints: Endpoints):
    first, second = mint(), mint(30)
    endpoints.valid_tokens.update({first, second})

    def me(headers: dict[str, str]) -> Response:
        return endpoints.client.get(ME, headers=SAME_ORIGIN | headers)

    with_first = me({"Cookie": f"{SESSION}={first}"})
    with_second = me({"Cookie": f"{SESSION}={second}"})
    with_bearer = me({"Authorization": f"Bearer {first}"})
    rejected = me({"Cookie": f"{SESSION}=not-a-token"})

    assert with_first.status_code == with_second.status_code == 200
    assert with_first.headers[GENERATION] == session_generation(first)
    assert with_second.headers[GENERATION] == session_generation(second)
    assert session_generation(first) != session_generation(second)
    assert first not in with_first.headers[GENERATION]
    # Only a session the browser holds as a cookie has a generation.
    assert with_bearer.status_code == 200
    assert GENERATION not in with_bearer.headers
    assert rejected.status_code == 401
    assert GENERATION not in rejected.headers
