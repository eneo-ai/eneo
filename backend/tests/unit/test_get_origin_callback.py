import json
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.datastructures import Headers

from eneo.allowed_origins import get_origin_callback as callback_module
from eneo.authentication.auth_models import ApiKeyPolicyResponse
from eneo.main.exceptions import ErrorCodes
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
