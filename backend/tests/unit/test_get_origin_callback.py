from types import SimpleNamespace

import pytest
from starlette.datastructures import Headers

from eneo.allowed_origins import get_origin_callback as callback_module
from eneo.authentication.auth_models import ApiKeyPolicyResponse
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
async def test_cors_middleware_passes_preflight_headers_to_callback():
    captured = None

    async def callback(origin, headers):
        nonlocal captured
        captured = (origin, headers.get("access-control-request-headers"))
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
    assert captured == ("https://key.example", "x-api-key")


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
    assert await callback_module.get_origin("https://app.key.example", headers)


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
    assert not await callback_module.get_origin("https://key.example", headers)
