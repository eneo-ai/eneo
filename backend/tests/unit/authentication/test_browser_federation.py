"""Browser federation preserves the same destination policy as the SPA."""

import hashlib
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from eneo.authentication import browser_session_router as routes
from eneo.authentication.browser_session import safe_next_path, txn_cookie_name
from eneo.authentication.federation_router import InitiateAuthResponse
from eneo.main.config import Settings, get_settings, set_settings
from eneo.server.endpoint_routes import endpoint_routes
from eneo.server.main import get_application
from tests.unit.browser_session_test_utils import expected_set_cookie

INITIATE = "/api/v1/auth/browser/initiate"
CALLBACKS = ("/login/callback", "/auth/callback")
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
TXN = "browser-transaction-sentinel"


CASES = json.loads(
    (
        Path(__file__).resolve().parents[4]
        / "frontend/apps/web-next/src/lib/auth/safe-next.cases.json"
    ).read_text()
)


@pytest.mark.parametrize("value", CASES["keep"])
def test_safe_next_keeps_page_destinations(value: str) -> None:
    assert safe_next_path(value) == value


@pytest.mark.parametrize("value", CASES["reject"])
def test_safe_next_refuses_non_pages(value: str | None) -> None:
    assert safe_next_path(value) == "/spaces/personal/chat"


@pytest.fixture(autouse=True)
def browser_settings() -> Iterator[Settings]:
    original = get_settings()
    settings = original.model_copy(
        update={
            "browser_session_enabled": True,
            "web_app_enabled": False,
            "environment": "production",
        }
    )
    set_settings(settings)
    yield settings
    set_settings(original)


def signed_state(next_path: str = "/dashboard", **claims: object) -> str:
    return jwt.encode(
        {
            "frontend_state": hashlib.sha256(TXN.encode()).hexdigest()
            + ":"
            + next_path,
            "exp": int(time.time()) + 600,
            **claims,
        },
        get_settings().jwt_secret,
        algorithm="HS256",
    )


@dataclass
class Federation:
    client: TestClient
    initiate: AsyncMock
    callback: AsyncMock


@pytest.fixture
def federation(monkeypatch: pytest.MonkeyPatch) -> Iterator[Federation]:
    initiate = AsyncMock(
        return_value=InitiateAuthResponse(
            authorization_url="https://idp.example/authorize?state=server-state",
            state="server-state",
        )
    )
    token = jwt.encode(
        {"exp": int(time.time()) + 900}, get_settings().jwt_secret, algorithm="HS256"
    )
    callback = AsyncMock(
        return_value={"access_token": token, "frontend_state": "ignored"}
    )
    monkeypatch.setattr(routes, "initiate_auth", initiate, raising=False)
    monkeypatch.setattr(routes, "auth_callback", callback, raising=False)
    app = get_application()
    for route in endpoint_routes(app.routes):
        if route.path in (INITIATE, *CALLBACKS) and route.dependant:
            for dependency in route.dependant.dependencies:
                if dependency.name == "container":
                    app.dependency_overrides[dependency.call] = lambda: object()
    client = TestClient(app, base_url="https://beta.example.se", follow_redirects=False)
    try:
        yield Federation(client, initiate, callback)
    finally:
        client.close()


def detail_code(response) -> str:
    return parse_qs(urlsplit(response.headers["location"]).query)["detailCode"][0]


def test_initiate_binds_transaction_and_registered_host(federation: Federation) -> None:
    response = federation.client.get(
        INITIATE,
        params={"tenant": "city", "next": "/dashboard?tab=a"},
        headers=SAME_ORIGIN,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("https://idp.example/authorize")
    assert response.headers["cache-control"] == "no-store"
    transaction = federation.client.cookies[txn_cookie_name(get_settings())]
    assert response.headers["set-cookie"] == expected_set_cookie(
        "__Host-eneo_oidc_txn",
        transaction,
        get_settings().oidc_state_ttl_seconds,
        production=True,
    )
    kwargs = federation.initiate.await_args.kwargs
    assert kwargs["redirect_uri_param"] == "https://beta.example.se/login/callback"
    assert kwargs["tenant"] == "city"
    assert (
        kwargs["state"]
        == hashlib.sha256(transaction.encode()).hexdigest() + ":/dashboard?tab=a"
    )


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_initiate_refuses_other_sites(federation: Federation, site: str) -> None:
    response = federation.client.get(INITIATE, headers={"Sec-Fetch-Site": site})
    assert response.status_code == 303
    assert detail_code(response) == "invalid_login_attempt"
    assert "set-cookie" not in response.headers
    federation.initiate.assert_not_awaited()


@pytest.mark.parametrize("prompt", ["select_account", "login", ""])
def test_initiate_rejects_prompt_without_clearing_session(
    federation: Federation, prompt: str
) -> None:
    response = federation.client.get(
        INITIATE, params={"prompt": prompt}, headers=SAME_ORIGIN
    )
    assert response.status_code == 400
    assert "set-cookie" not in response.headers
    federation.initiate.assert_not_awaited()


def test_initiate_tries_only_registered_callback_candidates(
    federation: Federation,
) -> None:
    federation.initiate.side_effect = [
        HTTPException(
            400, "The provided redirect_uri is not registered for this tenant."
        ),
        InitiateAuthResponse(
            authorization_url="https://idp.example/authorize", state="state"
        ),
    ]
    response = federation.client.get(INITIATE, headers=SAME_ORIGIN)
    assert response.status_code == 303
    assert [
        call.kwargs["redirect_uri_param"]
        for call in federation.initiate.await_args_list
    ] == [
        "https://beta.example.se/login/callback",
        "https://beta.example.se/auth/callback",
    ]


def test_unregistered_host_has_no_transaction(federation: Federation) -> None:
    federation.initiate.side_effect = HTTPException(
        400, "The provided redirect_uri is not registered for this tenant."
    )
    response = federation.client.get(INITIATE, headers=SAME_ORIGIN)
    assert detail_code(response) == "redirect_uri_not_registered"
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("path", CALLBACKS)
@pytest.mark.parametrize(
    "next_path,expected",
    [
        ("/dashboard", "/dashboard"),
        ("//evil.example", "/spaces/personal/chat"),
        ("/sök", "/s%C3%B6k"),
    ],
)
def test_callback_sets_session_and_clears_transaction(
    federation: Federation, path: str, next_path: str, expected: str
) -> None:
    federation.client.cookies.set("__Host-eneo_oidc_txn", TXN)
    response = federation.client.get(
        path,
        params={"code": "one-time-code", "state": signed_state(next_path)},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == expected
    cookies = response.headers.get_list("set-cookie")
    parsed = SimpleCookie()
    for cookie in cookies:
        parsed.load(cookie)
    assert 0 < int(parsed["__Host-eneo_web"]["max-age"]) <= 900
    assert any(
        cookie.startswith("__Host-eneo_web=")
        and "; Secure" in cookie
        and "; HttpOnly" in cookie
        for cookie in cookies
    )
    assert (
        expected_set_cookie("__Host-eneo_oidc_txn", '""', 0, production=True) in cookies
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    federation.callback.assert_awaited_once()


@pytest.mark.parametrize(
    "case",
    [
        "missing-cookie",
        "wrong-cookie",
        "duplicate-cookie",
        "missing-state",
        "bad-signature",
        "expired-state",
        "missing-expiry",
        "wrong-binding-type",
        "unicode-binding",
    ],
)
def test_callback_rejects_invalid_transaction(
    federation: Federation, case: str
) -> None:
    cookie = "__Host-eneo_oidc_txn=" + TXN
    state = signed_state()
    if case == "missing-cookie":
        cookie = ""
    if case == "wrong-cookie":
        cookie += "wrong"
    if case == "duplicate-cookie":
        cookie += "; __Host-eneo_oidc_txn=" + TXN
    if case == "missing-state":
        state = ""
    if case == "bad-signature":
        state = jwt.encode(
            {"exp": int(time.time()) + 600},
            "different-test-signing-key-32-bytes-minimum",
            algorithm="HS256",
        )
    if case == "expired-state":
        state = signed_state(exp=1)
    if case == "missing-expiry":
        state = jwt.encode(
            {
                "frontend_state": hashlib.sha256(TXN.encode()).hexdigest()
                + ":/dashboard"
            },
            get_settings().jwt_secret,
            algorithm="HS256",
        )
    if case == "wrong-binding-type":
        state = signed_state(frontend_state=[])
    if case == "unicode-binding":
        state = signed_state(frontend_state="å:/dashboard")
    response = federation.client.get(
        CALLBACKS[0],
        params={"code": "one-time-code", "state": state},
        headers={"Cookie": cookie},
    )
    assert response.status_code == 303
    assert detail_code(response) == "invalid_login_attempt"
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert "next" not in query
    if case == "expired-state":
        assert query["rawDetail"] == [
            "Authorization session expired. Please try logging in again."
        ]
        assert query["correlation"]
    else:
        assert "rawDetail" not in query
    assert expected_set_cookie(
        "__Host-eneo_oidc_txn", '""', 0, production=True
    ) in response.headers.get_list("set-cookie")
    federation.callback.assert_not_awaited()


@pytest.mark.parametrize(
    "params,expected",
    [({"error": "access_denied"}, "identity_provider_error"), ({}, "no_code_received")],
)
@pytest.mark.parametrize("next_path", ["/dashboard?tab=team", "https://evil.example"])
def test_callback_reports_provider_and_missing_code(
    federation: Federation, params: dict[str, str], expected: str, next_path: str
) -> None:
    federation.client.cookies.set("__Host-eneo_oidc_txn", TXN)
    response = federation.client.get(
        CALLBACKS[0], params={"state": signed_state(next_path), **params}
    )
    assert detail_code(response) == expected
    assert parse_qs(urlsplit(response.headers["location"]).query)["next"] == [
        safe_next_path(next_path)
    ]
    federation.callback.assert_not_awaited()


@pytest.mark.parametrize("path", CALLBACKS)
@pytest.mark.parametrize("valid_signature", [True, False])
def test_expired_state_without_cookie_has_only_verified_expiry_diagnostics(
    federation: Federation, path: str, valid_signature: bool
) -> None:
    state = signed_state(exp=1)
    if not valid_signature:
        state = jwt.encode(
            {"exp": 1, "frontend_state": "untrusted:/private"},
            "different-test-signing-key-32-bytes-minimum",
            algorithm="HS256",
        )
    response = federation.client.get(
        path, params={"state": state, "code": "one-time-code"}
    )
    assert response.status_code == 303
    assert detail_code(response) == "invalid_login_attempt"
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert "next" not in query
    if valid_signature:
        assert query["rawDetail"] == [
            "Authorization session expired. Please try logging in again."
        ]
        assert query["correlation"]
    else:
        assert "rawDetail" not in query
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers.get_list("set-cookie") == [
        expected_set_cookie("__Host-eneo_oidc_txn", '""', 0, production=True)
    ]
    federation.callback.assert_not_awaited()


@pytest.mark.parametrize(
    "status,expected",
    [
        (403, "access_denied"),
        (401, "unauthorized"),
        (400, "http_400"),
        (500, "http_500"),
    ],
)
def test_callback_maps_backend_failure(
    federation: Federation, status: int, expected: str
) -> None:
    federation.client.cookies.set("__Host-eneo_oidc_txn", TXN)
    federation.callback.side_effect = HTTPException(
        status,
        "public-detail-" + "x" * 1200,
        headers={"X-Correlation-ID": "test-correlation"},
    )
    response = federation.client.get(
        CALLBACKS[0], params={"state": signed_state(), "code": "one-time-code"}
    )
    assert detail_code(response) == expected
    assert parse_qs(urlsplit(response.headers["location"]).query)["correlation"] == [
        "test-correlation"
    ]
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["next"] == ["/dashboard"]
    if status in (401, 403):
        assert "rawDetail" not in query
    else:
        assert query["rawDetail"] == [("public-detail-" + "x" * 1200)[:1000]]
    assert not any(
        cookie.startswith("__Host-eneo_web=")
        for cookie in response.headers.get_list("set-cookie")
    )


@pytest.mark.parametrize("path", [INITIATE, *CALLBACKS])
def test_disabled_browser_session_has_no_federation(
    federation: Federation, path: str, browser_settings: Settings
) -> None:
    browser_settings.browser_session_enabled = False
    response = federation.client.get(path)
    assert response.status_code == 404
    if path in CALLBACKS:
        assert expected_set_cookie(
            "__Host-eneo_oidc_txn", '""', 0, production=True
        ) in response.headers.get_list("set-cookie")
        assert response.headers["referrer-policy"] == "no-referrer"
    federation.initiate.assert_not_awaited()
    federation.callback.assert_not_awaited()


@pytest.mark.parametrize(
    "address,expected",
    [
        ("http://localhost:3101", "http://localhost:3101/login/callback"),
        ("http://127.0.0.1:3101", "http://127.0.0.1:3101/login/callback"),
        ("http://[::1]:3101", "http://[::1]:3101/login/callback"),
        ("http://beta.example.se", "https://beta.example.se/login/callback"),
    ],
)
def test_initiate_uses_loopback_http_only(
    federation: Federation, address: str, expected: str
) -> None:
    response = federation.client.get(
        INITIATE, headers={**SAME_ORIGIN, "Host": urlsplit(address).netloc}
    )
    assert response.status_code == 303
    assert federation.initiate.await_args.kwargs["redirect_uri_param"] == expected


def test_development_cookie_has_same_transaction_attributes(
    federation: Federation, browser_settings: Settings
) -> None:
    browser_settings.environment = "development"
    response = federation.client.get(INITIATE, headers=SAME_ORIGIN)
    value = federation.client.cookies["eneo_web_txn"]
    assert response.headers["set-cookie"] == expected_set_cookie(
        "eneo_web_txn", value, browser_settings.oidc_state_ttl_seconds, production=False
    )


def test_callback_never_exposes_unexpected_error(federation: Federation) -> None:
    federation.client.cookies.set("__Host-eneo_oidc_txn", TXN)
    federation.callback.side_effect = RuntimeError("private-upstream-sentinel")
    response = federation.client.get(
        CALLBACKS[0], params={"state": signed_state(), "code": "one-time-code"}
    )
    assert detail_code(response) == "http_500"
    assert "private-upstream-sentinel" not in response.headers["location"]
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["next"] == ["/dashboard"]
    assert "rawDetail" not in query
    assert expected_set_cookie(
        "__Host-eneo_oidc_txn", '""', 0, production=True
    ) in response.headers.get_list("set-cookie")
    assert not any(
        cookie.startswith("__Host-eneo_web=")
        for cookie in response.headers.get_list("set-cookie")
    )


@pytest.mark.parametrize(
    "failure,expected",
    [("unexpected", "http_500"), ("database", "http_500"), ("http", "access_denied")],
)
def test_callback_commit_failure_cannot_send_session(
    federation: Federation, failure: str, expected: str
) -> None:
    from sqlalchemy.exc import IntegrityError

    from eneo.database.database import get_session_with_transaction

    app = federation.client.app
    for route in endpoint_routes(app.routes):
        if route.path in CALLBACKS and route.dependant:
            for dependency in route.dependant.dependencies:
                if dependency.name == "container":
                    app.dependency_overrides.pop(dependency.call, None)

    async def failed_commit():
        yield object()
        if failure == "database":
            raise IntegrityError("private-statement", {}, Exception("private-error"))
        if failure == "http":
            raise HTTPException(403, "private-error")
        raise RuntimeError("commit-failed-sentinel")

    app.dependency_overrides[get_session_with_transaction] = failed_commit
    federation.client.cookies.set("__Host-eneo_oidc_txn", TXN)
    response = federation.client.get(
        CALLBACKS[0], params={"state": signed_state(), "code": "one-time-code"}
    )
    federation.callback.assert_awaited_once()
    assert detail_code(response) == expected
    assert response.content == b""
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["next"] == ["/dashboard"]
    assert "rawDetail" not in query
    assert response.headers["referrer-policy"] == "no-referrer"
    assert not any(
        cookie.startswith("__Host-eneo_web=")
        for cookie in response.headers.get_list("set-cookie")
    )
    assert expected_set_cookie(
        "__Host-eneo_oidc_txn", '""', 0, production=True
    ) in response.headers.get_list("set-cookie")


def test_callback_http_failure_rolls_back_before_redirect(
    federation: Federation,
) -> None:
    outcomes: list[str] = []

    async def transaction():
        try:
            yield object()
        except HTTPException:
            outcomes.append("rollback")
            raise
        else:
            outcomes.append("commit")

    app = federation.client.app
    for route in endpoint_routes(app.routes):
        if route.path in CALLBACKS and route.dependant:
            for dependency in route.dependant.dependencies:
                if dependency.name == "container":
                    app.dependency_overrides[dependency.call] = transaction
    federation.callback.side_effect = HTTPException(400, "Public refusal")
    federation.client.cookies.set("__Host-eneo_oidc_txn", TXN)
    response = federation.client.get(
        CALLBACKS[0], params={"state": signed_state(), "code": "one-time-code"}
    )
    assert outcomes == ["rollback"]
    assert response.status_code == 303
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["next"] == ["/dashboard"]
    assert query["rawDetail"] == ["Public refusal"]


@pytest.mark.asyncio
@pytest.mark.parametrize("redis_failure", [False, True])
async def test_real_federation_admits_one_callback_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch, browser_settings: Settings, redis_failure: bool
) -> None:
    import asyncio

    from httpx import ASGITransport, AsyncClient

    from eneo.authentication import federation_router
    from tests.unittests.authentication.test_federation_router import (
        FailingStateRedis,
        InterleavingRedis,
        _single_use_callback,
    )

    callback, container = await _single_use_callback(
        monkeypatch, FailingStateRedis() if redis_failure else InterleavingRedis()
    )
    browser_settings.jwt_secret = federation_router.get_settings().jwt_secret
    payload = jwt.decode(
        callback.state, browser_settings.jwt_secret, algorithms=["HS256"]
    )
    payload["frontend_state"] = hashlib.sha256(TXN.encode()).hexdigest() + ":/dashboard"
    state = jwt.encode(payload, browser_settings.jwt_secret, algorithm="HS256")
    token = jwt.encode(
        {"exp": int(time.time()) + 900}, browser_settings.jwt_secret, algorithm="HS256"
    )
    monkeypatch.setattr(
        container._auth_service, "create_access_token_for_user", lambda user: token
    )
    app = get_application()
    for route in endpoint_routes(app.routes):
        if route.path in CALLBACKS and route.dependant:
            for dependency in route.dependant.dependencies:
                if dependency.name == "container":
                    app.dependency_overrides[dependency.call] = lambda: container
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://beta.example.se",
        follow_redirects=False,
    ) as client:

        async def attempt():
            return await client.get(
                CALLBACKS[0],
                params={"state": state, "code": callback.code},
                headers={
                    "Cookie": "__Host-eneo_oidc_txn=" + TXN,
                    "Sec-Fetch-Site": "cross-site",
                },
            )

        responses = await asyncio.gather(attempt(), attempt())
        assert sum(r.headers["location"] == "/dashboard" for r in responses) == (
            0 if redis_failure else 1
        )
        for response in responses:
            assert response.status_code == 303
            if response.headers["location"] != "/dashboard":
                assert detail_code(response) == "http_400"
                assert not any(
                    cookie.startswith("__Host-eneo_web=")
                    for cookie in response.headers.get_list("set-cookie")
                )
            assert expected_set_cookie(
                "__Host-eneo_oidc_txn", '""', 0, production=True
            ) in response.headers.get_list("set-cookie")
        # Replaying after both responses cannot issue another session either.
        replay = await attempt()
        assert detail_code(replay) == "http_400"


@pytest.mark.asyncio
@pytest.mark.parametrize("registered_path", [None, *CALLBACKS])
async def test_real_initiate_writes_state_only_for_registered_callback(
    monkeypatch: pytest.MonkeyPatch, registered_path: str | None
) -> None:
    from httpx import ASGITransport, AsyncClient

    from eneo.authentication import federation_router
    from tests.unittests.authentication.test_federation_router import (
        FakeAioHttpClient,
        FakeRedis,
        FakeResponse,
        _single_use_callback,
    )

    redis = FakeRedis()
    _, container = await _single_use_callback(monkeypatch, redis)
    redis._store.clear()
    tenant = container._tenant_repo._tenant
    tenant.federation_config["additional_redirect_uris"] = (
        ["https://beta.example.se" + registered_path] if registered_path else []
    )
    monkeypatch.setattr(
        federation_router,
        "aiohttp_client",
        lambda: FakeAioHttpClient(
            FakeResponse({"authorization_endpoint": "https://idp.example/authorize"})
        ),
    )
    app = get_application()
    for route in endpoint_routes(app.routes):
        if route.path == INITIATE and route.dependant:
            for dependency in route.dependant.dependencies:
                if dependency.name == "container":
                    app.dependency_overrides[dependency.call] = lambda: container
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://beta.example.se"
    ) as client:
        response = await client.get(
            INITIATE,
            params={"tenant": tenant.slug, "next": "/dashboard"},
            headers=SAME_ORIGIN,
        )
        assert response.status_code == 303
        if registered_path is None:
            assert detail_code(response) == "redirect_uri_not_registered"
            assert redis._store == {}
            assert "set-cookie" not in response.headers
        else:
            query = parse_qs(urlsplit(response.headers["location"]).query)
            assert query["redirect_uri"] == [
                "https://beta.example.se" + registered_path
            ]
            assert len(redis._store) == 1
            state = jwt.decode(
                query["state"][0],
                federation_router.get_settings().jwt_secret,
                algorithms=["HS256"],
            )
            assert state["frontend_state"] == (
                hashlib.sha256(
                    client.cookies["__Host-eneo_oidc_txn"].encode()
                ).hexdigest()
                + ":/dashboard"
            )
