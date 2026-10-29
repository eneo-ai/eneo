"""Which credential OAUTH2_SCHEME hands to authentication.

A raw Authorization header is the only credential read, valid or not. An
API-key header rules the session cookie out. Otherwise the cookie counts, but
only with BROWSER_SESSION_ENABLED on and when the Sec-Fetch-Site gate allows.
"""

import logging
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient
from starlette.requests import Request

from eneo.authentication import browser_session
from eneo.authentication.api_key_v2_repo import ApiKeysV2Repository
from eneo.authentication.browser_session import (
    SESSION_GENERATION_HEADER,
    SessionGenerationMismatchError,
    session_generation,
)
from eneo.database.database import (
    AsyncSession,
    get_session,
    get_session_with_transaction,
)
from eneo.main.config import Settings, get_settings, set_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import AuthenticationException, NotFoundException
from eneo.main.logging import OTELJSONFormatter
from eneo.server.dependencies.auth_definitions import OAUTH2_SCHEME
from eneo.server.main import get_application
from eneo.users.user import UserInDB
from eneo.users.user_service import UserService
from tests.unit.test_endpoint_access import make_user

BEARER = "bearer-token-A"
COOKIE = "cookie-token-C"
SESSION = "__Host-eneo_web"
DEV_SESSION = "eneo_web"
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}


@pytest.fixture(autouse=True)
def original_settings() -> Iterator[Settings]:
    original = get_settings()
    use_settings(original)
    yield original
    set_settings(original)


def use_settings(base: Settings, **updates: object) -> Settings:
    settings = base.model_copy(
        update={"browser_session_enabled": True, "environment": "production"} | updates
    )
    set_settings(settings)
    return settings


def api_key_header() -> str:
    return get_settings().api_key_header_name


def make_request(
    method: str = "GET",
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> Request:
    raw = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in (headers or {}).items()
    ]
    if cookies:
        cookie = "; ".join(f"{name}={value}" for name, value in cookies.items())
        raw.append((b"cookie", cookie.encode("latin-1")))
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/v1/users/me/",
            "query_string": b"q=private",
            "headers": raw,
        }
    )


async def credential(
    method: str = "GET",
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> str | None:
    return await OAUTH2_SCHEME(make_request(method, headers, cookies))


WITH_COOKIE = {SESSION: COOKIE}
# Stands for the configured API-key header name in the cases below.
API_KEY = "api-key-header"


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        # 1. Bearer wins over the cookie.
        ({"Authorization": f"Bearer {BEARER}"}, BEARER),
        # 2. Bearer wins over the API key and the cookie.
        ({"Authorization": f"Bearer {BEARER}", API_KEY: "sk_k"}, BEARER),
        # 3. Any other Authorization scheme: no fallback to the cookie.
        ({"Authorization": "Basic eA=="}, None),
        # 4. An empty Authorization header or an empty Bearer: no fallback.
        ({"Authorization": ""}, None),
        ({"Authorization": "Bearer "}, None),
        # 5. An API-key header never falls back to the cookie, even empty.
        ({API_KEY: "sk_k"}, None),
        ({API_KEY: ""}, None),
    ],
)
async def test_explicit_credentials_win_over_the_cookie(
    headers: dict[str, str], expected: str | None
):
    headers = {
        (api_key_header() if name == API_KEY else name): value
        for name, value in headers.items()
    }
    # Same-origin, so the gate would accept the cookie: precedence decides.
    for method in ("GET", "POST"):
        assert await credential(method, SAME_ORIGIN | headers, WITH_COOKIE) == expected
        assert (
            await credential(
                method,
                SAME_ORIGIN | headers | {SESSION_GENERATION_HEADER: "other-page"},
                WITH_COOKIE,
            )
            == expected
        )


@pytest.mark.parametrize(
    ("method", "headers", "expected"),
    [
        # 6. Same-origin, any method.
        (
            "POST",
            SAME_ORIGIN | {SESSION_GENERATION_HEADER: session_generation(COOKIE)},
            COOKIE,
        ),
        ("GET", SAME_ORIGIN, COOKIE),
        # 7. A sibling or another tenant's host is same-site, not same-origin.
        ("GET", {"Sec-Fetch-Site": "same-site"}, None),
        ("POST", {"Sec-Fetch-Site": "same-site"}, None),
        # 8. Cross-site.
        ("GET", {"Sec-Fetch-Site": "cross-site"}, None),
        # 9. A user-initiated navigation reads, never writes.
        ("GET", {"Sec-Fetch-Site": "none"}, COOKIE),
        ("POST", {"Sec-Fetch-Site": "none"}, None),
        # 10. No Sec-Fetch-Site: a same-origin read or a non-browser client.
        ("GET", {}, COOKIE),
        ("POST", {}, None),
        # 10b. ... but never with an Origin, which every CORS request carries.
        ("GET", {"Origin": "https://sibling.example.se"}, None),
    ],
)
async def test_cookie_only_through_the_gate(
    method: str, headers: dict[str, str], expected: str | None
):
    assert await credential(method, headers, WITH_COOKIE) == expected


@pytest.mark.parametrize("method", ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("expected", [None, "matching", "stale", ""])
async def test_cookie_request_is_bound_to_the_sending_document(
    method: str, expected: str | None
):
    headers = dict(SAME_ORIGIN)
    if expected is not None:
        headers[SESSION_GENERATION_HEADER] = (
            session_generation(COOKIE) if expected == "matching" else expected
        )
    if expected == "matching" or (expected is None and method in {"GET", "HEAD"}):
        assert await credential(method, headers, WITH_COOKIE) == COOKIE
    else:
        with pytest.raises(SessionGenerationMismatchError):
            await credential(method, headers, WITH_COOKIE)


@pytest.mark.parametrize(
    ("method", "headers"),
    [
        ("POST", SAME_ORIGIN),
        ("GET", {"Sec-Fetch-Site": "none"}),
        ("GET", {}),
    ],
)
async def test_cookie_ignored_when_setting_off(
    original_settings: Settings, method: str, headers: dict[str, str]
):
    # 11.
    use_settings(original_settings, browser_session_enabled=False)

    assert await credential(method, headers, WITH_COOKIE) is None


@pytest.mark.parametrize(
    ("environment", "read", "ignored"),
    [
        ("production", SESSION, DEV_SESSION),
        ("development", DEV_SESSION, SESSION),
    ],
)
async def test_one_cookie_name_per_installation(
    original_settings: Settings, environment: str, read: str, ignored: str
):
    # 12. The name follows the environment, never the request.
    use_settings(original_settings, environment=environment)

    assert await credential("GET", SAME_ORIGIN, {read: COOKIE}) == COOKIE
    assert await credential("GET", SAME_ORIGIN, {ignored: COOKIE}) is None


@pytest.mark.parametrize(
    ("cookie_headers", "expected"),
    [
        # A browser's own serialization, and the same pairs without spaces.
        ([f"lang=sv; {SESSION}={COOKIE}; theme=dark"], COOKIE),
        ([f"lang=sv;{SESSION}={COOKIE}"], COOKIE),
        # HTTP/2 may split the Cookie header; every one of them is read.
        (["lang=sv", f"{SESSION}={COOKIE}"], COOKIE),
        # Two values: one may be planted, so neither counts.
        ([f"{SESSION}={COOKIE}; {SESSION}=planted"], None),
        ([f"{SESSION}={COOKIE}", f"{SESSION}=planted"], None),
        # A name the browser does not treat as __Host- (a sibling host can set
        # it) never reads as the session, though Starlette strips it to one.
        ([f"\xa0{SESSION}=planted"], None),
        ([f"\x85{SESSION}=planted"], None),
        ([f"{SESSION}={COOKIE}; \xa0{SESSION}=planted"], COOKIE),
        ([f"{SESSION}\xa0=planted"], None),
        ([f"{SESSION.upper()}=planted"], None),
        ([f"{SESSION}="], None),
    ],
)
async def test_session_cookie_is_read_exactly(
    cookie_headers: list[str], expected: str | None
):
    raw = [(b"cookie", header.encode("latin-1")) for header in cookie_headers]
    raw.append((b"sec-fetch-site", b"same-origin"))
    request = Request(
        {"type": "http", "method": "GET", "path": "/api/v1/users/me/", "headers": raw}
    )

    assert await OAUTH2_SCHEME(request) == expected


@pytest.fixture
def gate_log(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    # SimpleLogger does not propagate to the root logger caplog listens on.
    browser_session.logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        browser_session.logger.removeHandler(caplog.handler)


async def test_refusal_is_logged_without_the_cookie(
    gate_log: pytest.LogCaptureFixture,
):
    headers = {"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"}

    assert await credential("POST", headers, WITH_COOKIE) is None

    [record] = gate_log.records
    assert record.getMessage() == "browser_origin_refused"
    assert record.levelno == logging.WARNING
    assert (
        record.__dict__.items()
        >= {
            "method": "POST",
            "path": "/api/v1/users/me/",
            "sec_fetch_site": "cross-site",
            "origin": "https://evil.example",
        }.items()
    )
    formatted = OTELJSONFormatter().format(record)
    assert COOKIE not in formatted
    assert COOKIE not in repr(record.__dict__)
    assert "private" not in formatted


async def test_missing_sec_fetch_site_is_logged_as_missing(
    gate_log: pytest.LogCaptureFixture,
):
    assert await credential("POST", {}, WITH_COOKIE) is None

    [record] = gate_log.records
    assert getattr(record, "sec_fetch_site") == "missing"


async def test_no_cookie_logs_no_refusal(gate_log: pytest.LogCaptureFixture):
    # Header-less API clients without a session must not look like attacks.
    assert await credential("POST", {}) is None
    assert await credential("POST", {"Sec-Fetch-Site": "cross-site"}) is None

    assert gate_log.records == []


@pytest.fixture
def me_endpoint(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, list]]:
    """GET /api/v1/users/me/ through the real app, with authentication stubbed."""
    user = make_user()
    calls: list[dict[str, str | None]] = []

    async def authenticate(
        _self: UserService,
        token: str | None = None,
        api_key: str | None = None,
        with_quota_used: bool = False,
        request: Request | None = None,
    ) -> UserInDB:
        calls.append({"token": token, "api_key": api_key})
        if token is None and api_key is None:
            raise AuthenticationException("No authenticated user.")
        return user

    async def session() -> AsyncSession:
        database = AsyncMock(spec=AsyncSession)
        database.in_transaction.return_value = True
        return database

    monkeypatch.setattr(UserService, "authenticate", authenticate)
    monkeypatch.setattr(
        ApiKeysV2Repository,
        "get_latest_active_by_owner",
        AsyncMock(return_value=None),
    )
    app = get_application()
    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_session_with_transaction] = session
    client = TestClient(app)
    try:
        yield client, calls
    finally:
        client.close()


ME = "/api/v1/users/me/"
COOKIE_HEADER = {"Cookie": f"{SESSION}={COOKIE}"}


def test_me_authenticates_with_the_same_origin_cookie(me_endpoint):
    client, calls = me_endpoint

    response = client.get(ME, headers=COOKIE_HEADER | SAME_ORIGIN)

    assert response.status_code == 200
    assert calls
    assert all(call == {"token": COOKIE, "api_key": None} for call in calls)


def test_me_refuses_the_cross_site_cookie(me_endpoint):
    client, calls = me_endpoint

    response = client.get(ME, headers=COOKIE_HEADER | {"Sec-Fetch-Site": "cross-site"})

    assert response.status_code == 401
    assert calls == [{"token": None, "api_key": None}]


def test_bearer_request_ignores_the_cookie(me_endpoint):
    client, calls = me_endpoint
    bearer = {"Authorization": f"Bearer {BEARER}"} | SAME_ORIGIN

    without_cookie = client.get(ME, headers=bearer)
    calls_without_cookie = list(calls)
    calls.clear()
    with_cookie = client.get(ME, headers=bearer | COOKIE_HEADER)

    assert without_cookie.status_code == with_cookie.status_code == 200
    assert without_cookie.json() == with_cookie.json()
    assert calls == calls_without_cookie
    assert all(call == {"token": BEARER, "api_key": None} for call in calls)


@pytest.mark.parametrize("expected", [None, "matching", "stale"])
@pytest.mark.parametrize("operation", ["read", "mutation", "upload"])
def test_real_routes_refuse_the_wrong_document_before_authentication_or_work(
    me_endpoint, monkeypatch: pytest.MonkeyPatch, expected: str | None, operation: str
):
    from eneo.server.dependencies import container as container_dependencies

    client, auth_calls = me_endpoint
    domain = AsyncMock(side_effect=NotFoundException("Reached the domain service"))
    monkeypatch.setattr(UserService, "invalidate_sessions", domain)
    # A permitted upload should reach its domain service without using storage.
    refresh = AsyncMock()
    monkeypatch.setattr(
        container_dependencies.object_content_runtime,
        "refresh_object_store_configuration",
        refresh,
    )
    monkeypatch.setattr(
        container_dependencies, "load_container_upload_admission", AsyncMock()
    )
    headers = COOKIE_HEADER | SAME_ORIGIN
    if expected is not None:
        headers[SESSION_GENERATION_HEADER] = (
            session_generation(COOKIE) if expected == "matching" else expected
        )

    if operation == "read":
        response = client.get(ME, headers=headers)
    elif operation == "mutation":
        response = client.post("/api/v1/users/me/sessions/invalidate/", headers=headers)
    else:
        with Container.group_service.override(
            providers.Object(SimpleNamespace(get_group=domain))
        ):
            response = client.post(
                "/api/v1/groups/00000000-0000-0000-0000-000000000001/info-blobs/upload/",
                files={"file": ("document.txt", b"document", "text/plain")},
                headers=headers,
            )

    accepted = expected == "matching" or (expected is None and operation == "read")
    if accepted:
        assert response.status_code == (200 if operation == "read" else 404)
        assert auth_calls
        if operation != "read":
            domain.assert_awaited_once()
    else:
        assert response.status_code == 401, response.text
        assert response.json()["eneo_error_code"] == 9080
        assert SESSION_GENERATION_HEADER not in response.headers
        assert auth_calls == []
        domain.assert_not_awaited()
        refresh.assert_not_awaited()
