import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.datastructures import Headers

from eneo.allowed_origins import get_origin_callback as callback_module
from eneo.authentication.auth_models import ApiKeyPolicyResponse
from eneo.main.config import get_settings, set_settings
from eneo.main.exceptions import ErrorCodes
from eneo.server.main import get_application
from eneo.server.middleware import cors as cors_module
from eneo.server.middleware.cors import CORSMiddleware


class _AsyncContext:
    def __init__(self, value=None):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _Session:
    def begin(self):
        return _AsyncContext()


class _SessionManager:
    def session(self):
        return _AsyncContext(_Session())


def _settings():
    return SimpleNamespace(
        api_key_header_name="X-API-Key",
        api_key_hash_secret="test-secret",
        jwt_secret="test-jwt-secret",
        dev=False,
        testing=True,
        is_development=False,
    )


@pytest.fixture(autouse=True)
def _reset_preflight_origin_cache(monkeypatch):
    monkeypatch.setattr(callback_module, "_preflight_key_origin_patterns", ())
    monkeypatch.setattr(callback_module, "_preflight_key_origin_cache_expires_at", 0.0)


def _install_common_fakes(
    monkeypatch, *, tenant_origins=(), current_tenant_origins=None
):
    class AllowedOriginRepo:
        def __init__(self, session):  # noqa: ARG002
            pass

        async def get_all(self):
            return [SimpleNamespace(url=origin) for origin in tenant_origins]

        async def get_by_tenant(self, tenant_id):  # noqa: ARG002
            origins = (
                tenant_origins
                if current_tenant_origins is None
                else current_tenant_origins
            )
            return [SimpleNamespace(url=origin) for origin in origins]

    monkeypatch.setattr(callback_module, "sessionmanager", _SessionManager())
    monkeypatch.setattr(callback_module, "AllowedOriginRepository", AllowedOriginRepo)


def test_tenant_origin_requirement_is_enabled_by_default():
    assert ApiKeyPolicyResponse().require_tenant_allowed_origin is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("origin", "extra_headers", "expected_status"),
    [
        ("https://api.example.com", {}, 204),
        ("https://api.example.com:443", {}, 204),
        ("http://api.example.com", {}, 400),
        ("https://api.example.com:8443", {}, 400),
        ("https://other.example.com", {}, 400),
        ("https://api.example.com", {"Authorization": "Bearer token"}, 204),
        ("https://api.example.com", {"X-Widget-Key": "invalid"}, 400),
        # An empty API-key header is still an API-key request: no shortcut.
        ("https://api.example.com", {"X-Widget-Key": ""}, 400),
        # Bearer wins over any API-key header, as in authentication.
        (
            "https://api.example.com",
            {"Authorization": "Bearer token", "X-Widget-Key": ""},
            204,
        ),
        (
            "https://api.example.com",
            {"Authorization": "Bearer token", "X-Widget-Key": "invalid"},
            204,
        ),
        ("https://api.example.com:bad", {}, 400),
        ("https://api.example.com/path", {}, 400),
        (
            "http://other.example.com",
            {"X-Forwarded-Host": "other.example.com", "X-Forwarded-Proto": "http"},
            400,
        ),
    ],
)
async def test_cors_uses_request_origin_without_bypassing_api_keys(
    monkeypatch, origin, extra_headers, expected_status
):
    _install_common_fakes(monkeypatch)
    settings = _settings()
    settings.api_key_header_name = "X-Widget-Key"
    monkeypatch.setattr(callback_module, "get_settings", lambda: settings)
    reached_paths = []

    async def app(scope, receive, send):  # noqa: ARG001
        reached_paths.append(scope["path"])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    cors = CORSMiddleware(app, callback=callback_module.get_origin)
    async with AsyncClient(
        transport=ASGITransport(app=cors), base_url="https://api.example.com"
    ) as client:
        response = await client.post(
            "/api/v1/users/login/token/",
            headers={"Origin": origin, **extra_headers},
            data={"username": "test@example.com", "password": "test-only"},
        )

    assert response.status_code == expected_status
    assert reached_paths == (
        ["/api/v1/users/login/token/"] if expected_status == 204 else []
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base_url", "origin", "extra_headers", "expected_status"),
    [
        ("http://eneo.example.se", "https://eneo.example.se", {}, 204),
        ("http://eneo.example.se", "https://tenant-b.example.se", {}, 400),
        (
            "http://eneo.example.se",
            "https://eneo.example.se",
            {"X-Widget-Key": "invalid"},
            400,
        ),
        (
            "http://eneo.example.se",
            "https://eneo.example.se",
            {"X-Widget-Key": ""},
            400,
        ),
        (
            "http://eneo.example.se",
            "https://eneo.example.se",
            {"Authorization": "Bearer token", "X-Widget-Key": ""},
            204,
        ),
        (
            "http://eneo.example.se",
            "https://tenant-b.example.se",
            {"Authorization": "Bearer token", "X-Widget-Key": ""},
            400,
        ),
        ("http://eneo.example.se", "https://eneo.example.se:8443", {}, 400),
        (
            "http://eneo.example.se",
            "https://evil.example",
            {"X-Forwarded-Host": "evil.example"},
            400,
        ),
        ("https://eneo.example.se", "http://eneo.example.se", {}, 400),
    ],
)
async def test_same_host_origin_is_allowed_behind_tls_proxy(
    monkeypatch, base_url, origin, extra_headers, expected_status
):
    """Gunicorn does not trust X-Forwarded-Proto, so behind Traefik the
    backend sees http while the page is https on the same host."""
    _install_common_fakes(monkeypatch)
    settings = _settings()
    settings.api_key_header_name = "X-Widget-Key"
    monkeypatch.setattr(callback_module, "get_settings", lambda: settings)
    reached_paths = []

    async def app(scope, receive, send):  # noqa: ARG001
        reached_paths.append(scope["path"])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    cors = CORSMiddleware(app, callback=callback_module.get_origin)
    async with AsyncClient(
        transport=ASGITransport(app=cors), base_url=base_url
    ) as client:
        response = await client.post(
            "/api/v1/flows/",
            headers={"Origin": origin, "X-Forwarded-Proto": "https", **extra_headers},
        )

    assert response.status_code == expected_status
    assert reached_paths == (["/api/v1/flows/"] if expected_status == 204 else [])


def _environment(monkeypatch, environment):
    """The real settings in ``environment``: the owner decides what is development."""
    settings = get_settings().model_copy(update={"environment": environment})
    monkeypatch.setattr(callback_module, "get_settings", lambda: settings)


# Each loopback host with and without a port, over http and https, in the
# case a browser sends and in the case a hand-written client might.
_LOOPBACK_ORIGINS = [
    "http://localhost:5173",
    "http://localhost",
    "https://localhost:8443",
    "http://LocalHost:5173",
    "HTTP://LOCALHOST",
    "http://127.0.0.1",
    "http://127.0.0.1:8123",
    "http://[::1]:3000",
    "http://[::1]",
    "https://[::1]:8443",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", _LOOPBACK_ORIGINS)
@pytest.mark.parametrize(
    ("environment", "allowed"),
    [
        ("production", False),
        ("staging", False),
        ("test", False),
        ("development", True),
        ("Development", True),
        ("local", True),
    ],
)
async def test_loopback_origin_passes_only_in_development(
    monkeypatch, origin, environment, allowed
):
    """A page served from the user's own machine gets no credentialed CORS
    outside development unless the allowlist names it."""
    _install_common_fakes(monkeypatch)
    _environment(monkeypatch, environment)
    preflight = Headers({"Access-Control-Request-Method": "POST"})

    assert await callback_module.get_origin(origin, Headers()) is allowed
    assert (
        await callback_module.get_origin(origin, preflight, is_preflight=True)
        is allowed
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost.evil.example",
        "http://127.0.0.1.evil.example",
        "http://evil-localhost",
        "http://[::ffff:127.0.0.1]",
        "http://0.0.0.0:5173",
        "null",
        "http://[::1",
        "http://localhost:99999",
        "ws://localhost:5173",
    ],
)
async def test_development_trusts_only_the_exact_loopback_hosts(monkeypatch, origin):
    _install_common_fakes(monkeypatch)
    _environment(monkeypatch, "development")

    assert not await callback_module.get_origin(origin, Headers())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("origin", "pattern", "allowed"),
    [
        ("http://localhost:5173", "http://localhost:*", True),
        ("http://localhost", "http://localhost:*", True),
        ("http://[::1]:3000", "http://[::1]:*", True),
        ("http://[::1]", "http://[::1]:*", True),
        ("http://[::1]", "http://[::1]", True),
        ("https://[::1]", "https://[::1]", True),
        ("http://127.0.0.1", "http://127.0.0.1:*", True),
        ("http://127.0.0.1", "http://127.0.0.1", True),
        # One loopback name does not stand in for another, nor http for https.
        ("http://127.0.0.1:5173", "http://localhost:*", False),
        ("http://[::1]:5173", "http://localhost:*", False),
        ("https://localhost:5173", "http://localhost:*", False),
        ("https://[::1]", "http://[::1]:*", False),
    ],
)
async def test_production_accepts_the_loopback_origins_the_allowlist_names(
    monkeypatch, origin, pattern, allowed
):
    _install_common_fakes(monkeypatch, tenant_origins=(pattern,))
    _environment(monkeypatch, "production")
    preflight = Headers({"Access-Control-Request-Method": "POST"})

    assert await callback_module.get_origin(origin, Headers()) is allowed
    assert (
        await callback_module.get_origin(origin, preflight, is_preflight=True)
        is allowed
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("environment", "base_url", "origin", "expected_status"),
    [
        # The host's own page is same-origin in every environment, also over
        # the https retry for a TLS-terminating proxy.
        ("production", "http://localhost:8123", "http://localhost:8123", 204),
        ("production", "http://localhost:8123", "https://localhost:8123", 204),
        ("production", "http://127.0.0.1:8123", "https://127.0.0.1:8123", 204),
        ("production", "http://[::1]:8123", "https://[::1]:8123", 204),
        # Another loopback port is another origin; only development admits it.
        ("production", "http://localhost:8123", "http://localhost:5173", 400),
        ("production", "http://localhost:8123", "https://localhost:5173", 400),
        ("production", "http://localhost:8123", "https://127.0.0.1:8123", 400),
        ("development", "http://localhost:8123", "http://localhost:5173", 204),
        # The https retry never turns a loopback page into the proxied host.
        ("production", "http://eneo.example.se", "https://localhost", 400),
        ("production", "http://eneo.example.se", "https://127.0.0.1", 400),
        ("production", "http://eneo.example.se", "https://[::1]", 400),
        # An http page on an https request is not same-origin.
        ("production", "https://localhost:8123", "http://localhost:8123", 400),
        ("development", "https://localhost:8123", "http://localhost:8123", 204),
    ],
)
async def test_loopback_origin_through_the_tls_proxy_retry(
    monkeypatch, environment, base_url, origin, expected_status
):
    _install_common_fakes(monkeypatch)
    _environment(monkeypatch, environment)

    async def app(scope, receive, send):  # noqa: ARG001
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    cors = CORSMiddleware(app, callback=callback_module.get_origin)
    async with AsyncClient(
        transport=ASGITransport(app=cors), base_url=base_url
    ) as client:
        response = await client.post(
            "/api/v1/flows/",
            headers={"Origin": origin, "X-Forwarded-Proto": "https"},
        )

    assert response.status_code == expected_status


@pytest.fixture
def app_in():
    """The real application, with its CORS settings, in one environment."""
    original = get_settings()

    def build(environment: str) -> TestClient:
        set_settings(original.model_copy(update={"environment": environment}))
        return TestClient(get_application())

    yield build
    set_settings(original)


@pytest.mark.parametrize(
    ("environment", "accepted"), [("production", False), ("development", True)]
)
def test_credentialed_cors_headers_only_for_an_accepted_loopback_origin(
    monkeypatch, app_in, environment, accepted
):
    _install_common_fakes(monkeypatch)
    client = app_in(environment)
    origin = "http://localhost:5173"

    preflight = client.options(
        "/api/v1/users/me/",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    actual = client.get("/api/livez", headers={"Origin": origin})

    if accepted:
        assert (preflight.status_code, actual.status_code) == (200, 200)
        for response in (preflight, actual):
            assert response.headers["access-control-allow-origin"] == origin
            assert response.headers["access-control-allow-credentials"] == "true"
    else:
        assert (preflight.status_code, actual.status_code) == (400, 400)
        assert actual.json()["code"] == "disallowed_cors_origin"
        for response in (preflight, actual):
            assert "access-control-allow-origin" not in response.headers
        assert "access-control-allow-credentials" not in actual.headers


_MALFORMED_ORIGINS = [
    b"http://[::1",
    b"https://app.example:99999",
    b"https://[app.example]",
    b"https://\xc3\xa9.example",  # UTF-8 bytes; a browser sends punycode
    b"chrome-extension://app.example",
    b"null",
    b"",
]


@pytest.mark.parametrize("origin", _MALFORMED_ORIGINS)
@pytest.mark.parametrize(
    "tenant_origins", [(), ("https://app.example", "app.example", "http://[::1]:*")]
)
def test_malformed_origin_is_refused_with_400_not_500(
    monkeypatch, caplog, app_in, origin, tenant_origins
):
    """No Origin value turns the CORS check into a 500: one that does not parse
    as an http(s) origin is refused and logged like any unregistered origin."""
    _install_common_fakes(monkeypatch, tenant_origins=tenant_origins)
    monkeypatch.setattr(cors_module, "logger", logging.getLogger("test.cors"))
    caplog.set_level(logging.WARNING, logger="test.cors")
    client = app_in("production")

    preflight = client.options(
        "/api/v1/users/me/",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    actual = client.get("/api/livez", headers={"Origin": origin})

    assert (preflight.status_code, preflight.text) == (400, "Disallowed CORS origin")
    assert actual.status_code == 400
    assert actual.json()["code"] == "disallowed_cors_origin"
    for response in (preflight, actual):
        assert "access-control-allow-origin" not in response.headers
    assert [record.getMessage() for record in caplog.records] == [
        "CORS origin refused: GET /api/livez from origin " + origin.decode("latin-1")
    ]


@pytest.mark.asyncio
async def test_actual_request_cannot_use_preflight_origin_allowlist(monkeypatch):
    _install_common_fakes(monkeypatch)
    monkeypatch.setattr(callback_module, "get_settings", _settings)

    class ApiKeyRepo:
        def __init__(self, session):  # noqa: ARG002
            pass

        async def list_relaxed_tenant_public_key_origin_patterns(self):
            return ["https://key.example"]

    monkeypatch.setattr(callback_module, "ApiKeysV2Repository", ApiKeyRepo)
    application_called = False
    sent_messages = []

    async def app(scope, receive, send):  # noqa: ARG001
        nonlocal application_called
        application_called = True
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent_messages.append(message)

    cors = CORSMiddleware(
        app,
        allow_methods=["*"],
        allow_headers=["*"],
        callback=callback_module.get_origin,
    )
    scope = {
        "type": "http",
        "path": "/",
        "method": "OPTIONS",
        "headers": [
            (b"origin", b"https://key.example"),
            (b"access-control-request-method", b"POST"),
            (b"access-control-request-headers", b"x-api-key"),
        ],
    }
    await cors(scope, receive, send)
    assert sent_messages[0]["status"] == 200
    assert not application_called

    sent_messages.clear()
    await cors({**scope, "method": "POST"}, receive, send)
    assert sent_messages[0]["status"] == 400
    assert not application_called


@pytest.mark.asyncio
async def test_cors_middleware_passes_preflight_headers_to_callback():
    captured = None

    async def callback(origin, headers, is_preflight, request_url):
        nonlocal captured
        captured = (origin, headers.get("access-control-request-headers"), is_preflight)
        return True

    async def app(scope, receive, send):  # noqa: ARG001
        raise AssertionError("Preflight must not reach the application")

    cors = CORSMiddleware(
        app,
        allow_methods=["*"],
        allow_headers=["*"],
        callback=callback,
    )
    response = await cors.preflight_response(
        Headers(
            {
                "Origin": "https://key.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-api-key",
            }
        )
    )

    assert response.status_code == 200
    assert captured == ("https://key.example", "x-api-key", True)


@pytest.mark.asyncio
async def test_cors_middleware_rejects_origin_before_calling_application():
    application_called = False
    sent_messages = []

    async def callback(origin, headers, is_preflight, request_url):
        assert origin == "https://denied.example"
        assert headers["x-api-key"] == "pk_example"
        assert not is_preflight
        return False

    async def app(scope, receive, send):  # noqa: ARG001
        nonlocal application_called
        application_called = True

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent_messages.append(message)

    cors = CORSMiddleware(app, callback=callback)
    await cors(
        {
            "type": "http",
            "path": "/",
            "method": "POST",
            "headers": [
                (b"origin", b"https://denied.example"),
                (b"x-api-key", b"pk_example"),
            ],
        },
        receive,
        send,
    )

    assert not application_called
    assert sent_messages[0]["status"] == 400


@pytest.mark.asyncio
async def test_rejected_origin_answers_in_the_api_error_contract():
    """A caller that forwards a browser Origin reads this body, so it carries
    the same shape and a machine code like every other 400."""

    async def callback(origin, headers, is_preflight, request_url):  # noqa: ARG001
        return False

    async def app(scope, receive, send):  # noqa: ARG001
        raise AssertionError("application must not be called")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    sent_messages = []

    async def send(message):
        sent_messages.append(message)

    cors = CORSMiddleware(app, callback=callback)
    await cors(
        {
            "type": "http",
            "path": "/api/v1/flows/",
            "method": "POST",
            "headers": [(b"origin", b"https://proxy.example")],
        },
        receive,
        send,
    )

    start, body = sent_messages[0], sent_messages[1]
    headers = Headers(raw=start["headers"])
    assert start["status"] == 400
    assert headers["content-type"] == "application/json"
    assert headers["vary"] == "Origin"
    assert json.loads(body["body"]) == {
        "message": (
            "Origin is not allowed. A server-side caller should not forward "
            "the browser Origin header."
        ),
        "eneo_error_code": ErrorCodes.BAD_REQUEST.value,
        "code": "disallowed_cors_origin",
        "context": {"origin": "https://proxy.example"},
    }


@pytest.mark.asyncio
async def test_cors_middleware_calls_application_after_origin_is_allowed():
    application_called = False
    sent_messages = []

    async def callback(origin, headers, is_preflight, request_url):  # noqa: ARG001
        return True

    async def app(scope, receive, send):  # noqa: ARG001
        nonlocal application_called
        application_called = True
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent_messages.append(message)

    cors = CORSMiddleware(app, callback=callback)
    await cors(
        {
            "type": "http",
            "path": "/",
            "method": "POST",
            "headers": [(b"origin", b"https://allowed.example")],
        },
        receive,
        send,
    )

    response_headers = Headers(raw=sent_messages[0]["headers"])
    assert application_called
    assert sent_messages[0]["status"] == 204
    assert response_headers["access-control-allow-origin"] == (
        "https://allowed.example"
    )


@pytest.mark.asyncio
async def test_tenant_origin_is_always_allowed(monkeypatch):
    _install_common_fakes(monkeypatch, tenant_origins=("https://tenant.example",))
    monkeypatch.setattr(
        callback_module,
        "get_settings",
        _settings,
    )

    assert await callback_module.get_origin("https://tenant.example", Headers())


@pytest.mark.asyncio
async def test_strict_tenant_policy_rejects_key_only_origin(monkeypatch):
    _install_common_fakes(monkeypatch)
    monkeypatch.setattr(
        callback_module,
        "get_settings",
        _settings,
    )

    class ApiKeyRepo:
        def __init__(self, session):  # noqa: ARG002
            pass

        async def tenant_requires_allowed_origin(self, tenant_id):
            assert tenant_id == "tenant-id"
            return True

    key = SimpleNamespace(
        tenant_id="tenant-id",
        key_type="pk_",
        allowed_origins=["https://key.example"],
        revoked_at=None,
        suspended_at=None,
        expires_at=None,
        rotation_grace_until=None,
    )

    class Resolver:
        def __init__(self, repo):  # noqa: ARG002
            pass

        async def resolve(self, plain_key):  # noqa: ARG002
            return SimpleNamespace(key=key)

    monkeypatch.setattr(callback_module, "ApiKeysV2Repository", ApiKeyRepo)
    monkeypatch.setattr(callback_module, "ApiKeyAuthResolver", Resolver)

    headers = Headers({"X-API-Key": "pk_example"})
    assert not await callback_module.get_origin("https://key.example", headers)


@pytest.mark.asyncio
async def test_strict_policy_does_not_use_another_tenants_origin(monkeypatch):
    _install_common_fakes(
        monkeypatch,
        tenant_origins=("https://key.example",),
        current_tenant_origins=(),
    )
    monkeypatch.setattr(callback_module, "get_settings", _settings)

    class ApiKeyRepo:
        def __init__(self, session):  # noqa: ARG002
            pass

        async def tenant_requires_allowed_origin(self, tenant_id):  # noqa: ARG002
            return True

    key = SimpleNamespace(
        tenant_id="tenant-id",
        key_type="pk_",
        allowed_origins=["https://key.example"],
        revoked_at=None,
        suspended_at=None,
        expires_at=None,
        rotation_grace_until=None,
    )

    class Resolver:
        def __init__(self, repo):  # noqa: ARG002
            pass

        async def resolve(self, plain_key):  # noqa: ARG002
            return SimpleNamespace(key=key)

    monkeypatch.setattr(callback_module, "ApiKeysV2Repository", ApiKeyRepo)
    monkeypatch.setattr(callback_module, "ApiKeyAuthResolver", Resolver)

    headers = Headers({"X-API-Key": "pk_example"})
    assert not await callback_module.get_origin("https://key.example", headers)


@pytest.mark.asyncio
async def test_relaxed_policy_uses_current_public_key_origin(monkeypatch):
    _install_common_fakes(monkeypatch)
    monkeypatch.setattr(
        callback_module,
        "get_settings",
        _settings,
    )

    class ApiKeyRepo:
        def __init__(self, session):  # noqa: ARG002
            pass

        async def tenant_requires_allowed_origin(self, tenant_id):
            assert tenant_id == "tenant-id"
            return False

    key = SimpleNamespace(
        tenant_id="tenant-id",
        key_type="pk_",
        allowed_origins=["https://key.example"],
        revoked_at=None,
        suspended_at=None,
        expires_at=None,
        rotation_grace_until=None,
    )

    class Resolver:
        def __init__(self, repo):  # noqa: ARG002
            pass

        async def resolve(self, plain_key):
            assert plain_key == "pk_example"
            return SimpleNamespace(key=key)

    monkeypatch.setattr(callback_module, "ApiKeysV2Repository", ApiKeyRepo)
    monkeypatch.setattr(callback_module, "ApiKeyAuthResolver", Resolver)

    headers = Headers({"X-API-Key": "pk_example"})
    assert await callback_module.get_origin("https://key.example", headers)
    assert not await callback_module.get_origin("https://other.example", headers)


@pytest.mark.asyncio
async def test_relaxed_policy_without_api_key_still_requires_tenant_origin(monkeypatch):
    _install_common_fakes(monkeypatch)
    monkeypatch.setattr(
        callback_module,
        "get_settings",
        _settings,
    )

    class ApiKeyRepo:
        def __init__(self, session):  # noqa: ARG002
            pass

    monkeypatch.setattr(callback_module, "ApiKeysV2Repository", ApiKeyRepo)

    assert not await callback_module.get_origin("https://key.example", Headers())


@pytest.mark.asyncio
async def test_bearer_token_takes_precedence_over_api_key_origin(monkeypatch):
    _install_common_fakes(monkeypatch)
    monkeypatch.setattr(callback_module, "get_settings", _settings)

    class ApiKeyRepo:
        def __init__(self, session):  # noqa: ARG002
            pass

    class Resolver:
        def __init__(self, repo):  # noqa: ARG002
            pass

        async def resolve(self, plain_key):  # noqa: ARG002
            raise AssertionError(
                "API key must not be resolved when bearer auth is used"
            )

    monkeypatch.setattr(callback_module, "ApiKeysV2Repository", ApiKeyRepo)
    monkeypatch.setattr(callback_module, "ApiKeyAuthResolver", Resolver)

    headers = Headers({"Authorization": "Bearer token", "X-API-Key": "pk_example"})
    assert not await callback_module.get_origin("https://key.example", headers)


@pytest.mark.asyncio
async def test_api_key_preflight_uses_active_public_key_origins(monkeypatch):
    _install_common_fakes(monkeypatch)
    monkeypatch.setattr(
        callback_module,
        "get_settings",
        _settings,
    )

    class ApiKeyRepo:
        def __init__(self, session):  # noqa: ARG002
            pass

        async def list_relaxed_tenant_public_key_origin_patterns(self):
            return ["https://*.key.example"]

    monkeypatch.setattr(callback_module, "ApiKeysV2Repository", ApiKeyRepo)

    headers = Headers(
        {
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, x-api-key",
        }
    )
    assert await callback_module.get_origin(
        "https://app.key.example", headers, is_preflight=True
    )


@pytest.mark.asyncio
async def test_api_key_preflight_origin_patterns_are_cached(monkeypatch):
    _install_common_fakes(monkeypatch)
    monkeypatch.setattr(callback_module, "get_settings", _settings)
    query_count = 0

    class ApiKeyRepo:
        def __init__(self, session):  # noqa: ARG002
            pass

        async def list_relaxed_tenant_public_key_origin_patterns(self):
            nonlocal query_count
            query_count += 1
            return ["https://*.key.example"]

    monkeypatch.setattr(callback_module, "ApiKeysV2Repository", ApiKeyRepo)

    headers = Headers(
        {
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-api-key",
        }
    )
    assert await callback_module.get_origin(
        "https://one.key.example", headers, is_preflight=True
    )
    assert await callback_module.get_origin(
        "https://two.key.example", headers, is_preflight=True
    )
    assert query_count == 1


@pytest.mark.asyncio
async def test_bearer_preflight_does_not_use_api_key_origins(monkeypatch):
    _install_common_fakes(monkeypatch)
    monkeypatch.setattr(callback_module, "get_settings", _settings)

    class ApiKeyRepo:
        def __init__(self, session):  # noqa: ARG002
            pass

        async def list_relaxed_tenant_public_key_origin_patterns(self):
            raise AssertionError("Bearer preflight must not query API key origins")

    monkeypatch.setattr(callback_module, "ApiKeysV2Repository", ApiKeyRepo)

    headers = Headers(
        {
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, x-api-key",
        }
    )
    assert not await callback_module.get_origin(
        "https://key.example", headers, is_preflight=True
    )


@pytest.mark.asyncio
async def test_preflight_without_api_key_header_still_requires_tenant_origin(
    monkeypatch,
):
    _install_common_fakes(monkeypatch)
    monkeypatch.setattr(
        callback_module,
        "get_settings",
        _settings,
    )

    class ApiKeyRepo:
        def __init__(self, session):  # noqa: ARG002
            pass

    monkeypatch.setattr(callback_module, "ApiKeysV2Repository", ApiKeyRepo)

    headers = Headers(
        {
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        }
    )
    assert not await callback_module.get_origin(
        "https://key.example", headers, is_preflight=True
    )


def _install_secret_key(monkeypatch, *, revoked_at=None, expires_at=None):
    """A resolved ``sk_`` key for a tenant whose allowlist is empty."""

    class ApiKeyRepo:
        def __init__(self, session):  # noqa: ARG002
            pass

        async def tenant_requires_allowed_origin(self, tenant_id):  # noqa: ARG002
            return True

    key = SimpleNamespace(
        tenant_id="tenant-id",
        key_type="sk_",
        allowed_origins=None,
        revoked_at=revoked_at,
        suspended_at=None,
        expires_at=expires_at,
        rotation_grace_until=None,
    )

    class Resolver:
        def __init__(self, repo):  # noqa: ARG002
            pass

        async def resolve(self, plain_key):
            assert plain_key == "sk_example"
            return SimpleNamespace(key=key)

    monkeypatch.setattr(callback_module, "ApiKeysV2Repository", ApiKeyRepo)
    monkeypatch.setattr(callback_module, "ApiKeyAuthResolver", Resolver)


@pytest.mark.asyncio
async def test_active_secret_key_is_not_subject_to_the_origin_allowlist(monkeypatch):
    """A server-to-server caller that forwards a browser Origin keeps working.

    Secret keys carry no origin restrictions by policy; the CORS allowlist
    exists for browser credentials. Before this rule an ``sk_`` request with an
    unregistered Origin was refused with 400 ``disallowed_cors_origin`` before
    authentication ran (#1046).
    """
    _install_common_fakes(monkeypatch)
    monkeypatch.setattr(callback_module, "get_settings", _settings)
    _install_secret_key(monkeypatch)

    headers = Headers({"X-API-Key": "sk_example"})
    assert await callback_module.get_origin("https://integration.example", headers)


@pytest.mark.asyncio
async def test_inactive_secret_key_still_needs_a_registered_origin(monkeypatch):
    """The middleware stays fail-closed until authentication rejects the key."""
    _install_common_fakes(monkeypatch)
    monkeypatch.setattr(callback_module, "get_settings", _settings)
    _install_secret_key(
        monkeypatch, revoked_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    headers = Headers({"X-API-Key": "sk_example"})
    assert not await callback_module.get_origin("https://integration.example", headers)


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["http://[::1", "null"])
async def test_active_secret_key_passes_a_malformed_origin_without_an_error(
    monkeypatch, origin
):
    """The allowlist refuses an origin that does not parse; a secret key is
    exempt from the allowlist whatever Origin its caller attached."""
    _install_common_fakes(monkeypatch, tenant_origins=("https://app.example",))
    monkeypatch.setattr(callback_module, "get_settings", _settings)
    _install_secret_key(monkeypatch)

    assert not await callback_module.get_origin(origin, Headers())
    assert await callback_module.get_origin(
        origin, Headers({"X-API-Key": "sk_example"})
    )


@pytest.mark.asyncio
async def test_refused_origin_is_logged_without_headers_or_body(monkeypatch, caplog):
    """An operator can tie a caller's 400 to its unregistered origin."""
    _install_common_fakes(monkeypatch)
    monkeypatch.setattr(callback_module, "get_settings", _settings)
    # The module logger does not propagate to the root logger that caplog
    # listens on, so hand it a plain stdlib logger for this test.
    monkeypatch.setattr(cors_module, "logger", logging.getLogger("test.cors"))
    caplog.set_level(logging.WARNING, logger="test.cors")

    async def app(scope, receive, send):  # noqa: ARG001
        raise AssertionError("application must not run for a refused origin")

    cors = CORSMiddleware(app, callback=callback_module.get_origin)
    async with AsyncClient(
        transport=ASGITransport(app=cors), base_url="https://api.example.com"
    ) as client:
        response = await client.post(
            "/api/v1/users/login/token/",
            headers={
                "Origin": "https://other.example",
                "Authorization": "Bearer s3cret",
            },
            data={"username": "test@example.com", "password": "test-only"},
        )

    assert response.status_code == 400
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert record.getMessage() == (
        "CORS origin refused: POST /api/v1/users/login/token/ from origin https://other.example"
    )
    assert "s3cret" not in caplog.text
    assert "test-only" not in caplog.text
