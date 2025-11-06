"""Unit tests for OIDC federation router edge cases."""

import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException

from intric.authentication import federation_router
from intric.authentication.federation_router import CallbackRequest
from intric.settings.encryption_service import EncryptionService
from intric.tenants.tenant import TenantInDB, TenantState
from intric.users.user import UserInDB


class DummySettings(SimpleNamespace):
    def __init__(self, **overrides):
        defaults = {
            "jwt_secret": "unit-test-secret",
            "oidc_state_ttl_seconds": 600,
            "oidc_redirect_grace_period_seconds": 900,
            "strict_oidc_redirect_validation": True,
            "tenant_credentials_enabled": False,
            "federation_per_tenant_enabled": False,
            "public_origin": "https://global.example.com",
            "openai_api_key": None,
            "anthropic_api_key": None,
            "azure_api_key": None,
            "berget_api_key": None,
            "mistral_api_key": None,
            "ovhcloud_api_key": None,
            "vllm_api_key": None,
            "oidc_discovery_endpoint": None,
            "oidc_client_secret": None,
            "oidc_client_id": None,
            "oidc_tenant_id": None,
        }
        defaults.update(overrides)
        super().__init__(**defaults)


class FakeRedis:
    def __init__(self):
        self._store: dict[str, str] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:  # noqa: ARG002
        self._store[key] = value

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200, headers: dict | None = None):
        self._payload = payload
        self.status = status
        self.headers = headers or {"content-type": "application/json"}
        # Pre-encode body for read() method
        self._body_bytes = json.dumps(self._payload).encode("utf-8")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return json.dumps(self._payload)

    async def read(self):
        """Return response body as bytes (for new wrapper function)."""
        return self._body_bytes


class FakeSession:
    """Fake aiohttp session that supports .request() method."""

    def __init__(self, response: FakeResponse):
        self._response = response

    def request(self, method: str, url: str, **kwargs):  # noqa: ARG002
        """Return the configured response for any request."""
        return self._response

    def post(self, *args, **kwargs):  # noqa: ARG002
        """Legacy method for backwards compatibility."""
        return self._response

    def get(self, *args, **kwargs):  # noqa: ARG002
        """Support GET requests."""
        return self._response


class FakeAioHttpClient:
    """Fake aiohttp client context manager."""

    def __init__(self, response: FakeResponse):
        self._response = response

    async def __aenter__(self):
        return FakeSession(self._response)

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    def post(self, *args, **kwargs):  # noqa: ARG002
        """Legacy method for backwards compatibility."""
        return self._response


class FakeJWKClient:
    def __init__(self, jwks_uri: str):  # noqa: ARG002
        pass

    def get_signing_key_from_jwt(self, _: str):
        class Key:
            key = "fake-key"

        return Key()


class TenantRepoStub:
    def __init__(self, tenant: TenantInDB):
        self._tenant = tenant

    async def get_by_slug(self, slug: str) -> TenantInDB | None:
        if self._tenant.slug == slug:
            return self._tenant
        return None

    async def get(self, tenant_id):
        if self._tenant.id == tenant_id:
            return self._tenant
        return None


class UserRepoStub:
    def __init__(self, user: UserInDB):
        self._user = user

    async def get_user_by_email(self, email: str):
        if email.lower() == self._user.email.lower():
            return self._user
        return None


class AuthServiceStub:
    def get_payload_from_openid_jwt(self, **kwargs):  # noqa: ARG002
        return {"email": "user@Example.COM"}

    def create_access_token_for_user(self, user: UserInDB):  # noqa: ARG002
        return "access-token"


class AuthServiceInvalidEmailStub:
    def __init__(self, email: str):
        self._email = email

    def get_payload_from_openid_jwt(self, **kwargs):  # noqa: ARG002
        return {"email": self._email}

    def create_access_token_for_user(self, user: UserInDB):  # noqa: ARG002
        return "access-token"


class MockContainer:
    def __init__(self, *, tenant_repo, user_repo, auth_service, redis_client, encryption_service):
        self._tenant_repo = tenant_repo
        self._user_repo = user_repo
        self._auth_service = auth_service
        self._redis_client = redis_client
        self._encryption_service = encryption_service

    def tenant_repo(self):
        return self._tenant_repo

    def encryption_service(self):
        return self._encryption_service

    def redis_client(self):
        return self._redis_client

    def auth_service(self):
        return self._auth_service

    def user_repo(self):
        return self._user_repo


@pytest.mark.asyncio
async def test_initiate_auth_blocks_inactive_tenant(monkeypatch):
    tenant = TenantInDB(
        id=uuid4(),
        name="Suspended",
        display_name="Suspended",
        quota_limit=1024**3,
        slug="suspended",
        state=TenantState.SUSPENDED,
        modules=[],
        api_credentials={},
        federation_config={},
    )

    dummy_settings = DummySettings()
    monkeypatch.setattr(federation_router, "get_settings", lambda: dummy_settings)

    container = MockContainer(
        tenant_repo=TenantRepoStub(tenant),
        user_repo=None,
        auth_service=None,
        redis_client=FakeRedis(),
        encryption_service=EncryptionService(None),
    )

    with pytest.raises(HTTPException) as exc:
        await federation_router.initiate_auth(tenant="suspended", state=None, container=container)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_auth_callback_accepts_recent_redirect_change(monkeypatch):
    dummy_settings = DummySettings()
    monkeypatch.setattr(federation_router, "get_settings", lambda: dummy_settings)

    redis_client = FakeRedis()
    tenant_id = uuid4()
    slug = "tenant-a"
    old_version = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()

    tenant = TenantInDB(
        id=tenant_id,
        name="Tenant A",
        display_name="Tenant A",
        slug=slug,
        quota_limit=1024**3,
        state=TenantState.ACTIVE,
        modules=[],
        api_credentials={},
        federation_config={
            "provider": "entra",
            "client_id": "client",
            "client_secret": "secret",
            "discovery_endpoint": "https://idp.example.com/.well-known/openid-configuration",
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
            "jwks_uri": "https://idp.example.com/jwks",
            "canonical_public_origin": "https://new.tenant.example.com",
            "redirect_path": "/login/callback",
            "allowed_domains": ["Example.COM"],
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    user = UserInDB(
        id=uuid4(),
        username="Tester",
        email="user@Example.COM",
        salt="salt",
        password="hashed123",
        used_tokens=0,
        tenant_id=tenant_id,
        tenant=tenant,
        quota_limit=1024**3,
        user_groups=[],
        roles=[],
        state="active",
    )

    container = MockContainer(
        tenant_repo=TenantRepoStub(tenant),
        user_repo=UserRepoStub(user),
        auth_service=AuthServiceStub(),
        redis_client=redis_client,
        encryption_service=EncryptionService(None),
    )

    issue_time = int(time.time())
    state_payload = {
        "tenant_id": str(tenant_id),
        "tenant_slug": slug,
        "frontend_state": "",
        "nonce": "nonce",
        "redirect_uri": "https://old.tenant.example.com/login/callback",
        "correlation_id": "corr-123",
        "exp": issue_time + 600,
        "iat": issue_time,
        "config_version": old_version,
    }

    signed_state = jwt.encode(state_payload, dummy_settings.jwt_secret, algorithm="HS256")

    cache_payload = {
        "tenant_id": str(tenant_id),
        "tenant_slug": slug,
        "redirect_uri": state_payload["redirect_uri"],
        "config_version": old_version,
        "iat": state_payload["iat"],
    }
    await redis_client.setex(
        f"oidc:state:{state_payload['nonce']}",  # Use nonce, not full JWT
        dummy_settings.oidc_state_ttl_seconds,
        json.dumps(cache_payload),
    )

    # Simulate canonical origin update during login
    tenant.federation_config["canonical_public_origin"] = "https://new.tenant.example.com"
    tenant.updated_at = datetime.now(timezone.utc)

    fake_response = FakeResponse({"id_token": "id", "access_token": "token"})
    monkeypatch.setattr(
        federation_router,
        "aiohttp_client",
        lambda: FakeAioHttpClient(fake_response),
    )
    monkeypatch.setattr(federation_router, "PyJWKClient", FakeJWKClient)
    monkeypatch.setattr(federation_router, "JWKClient", FakeJWKClient)

    callback = CallbackRequest(code="auth-code", state=signed_state)

    result = await federation_router.auth_callback(callback, container=container)

    assert result == {"access_token": "access-token"}
    assert redis_client._store == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_email", ["@example.com", "user@@example.com"])
async def test_auth_callback_rejects_invalid_email_format(monkeypatch, bad_email):
    dummy_settings = DummySettings()
    monkeypatch.setattr(federation_router, "get_settings", lambda: dummy_settings)

    redis_client = FakeRedis()
    tenant_id = uuid4()
    slug = "tenant-invalid-email"

    tenant = TenantInDB(
        id=tenant_id,
        name="Tenant Invalid",
        display_name="Tenant Invalid",
        slug=slug,
        quota_limit=1024**3,
        state=TenantState.ACTIVE,
        modules=[],
        api_credentials={},
        federation_config={
            "provider": "entra",
            "client_id": "client",
            "client_secret": "secret",
            "discovery_endpoint": "https://idp.example.com/.well-known/openid-configuration",
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
            "jwks_uri": "https://idp.example.com/jwks",
            "canonical_public_origin": "https://tenant.invalid",
            "redirect_path": "/login/callback",
            "allowed_domains": ["example.com"],
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    user = UserInDB(
        id=uuid4(),
        username="Tester",
        email="backup@example.com",
        salt="salt",
        password="hashed123",
        used_tokens=0,
        tenant_id=tenant_id,
        tenant=tenant,
        quota_limit=1024**3,
        user_groups=[],
        roles=[],
        state="active",
    )

    container = MockContainer(
        tenant_repo=TenantRepoStub(tenant),
        user_repo=UserRepoStub(user),
        auth_service=AuthServiceInvalidEmailStub(bad_email),
        redis_client=redis_client,
        encryption_service=EncryptionService(None),
    )

    issue_time = int(time.time())
    state_payload = {
        "tenant_id": str(tenant_id),
        "tenant_slug": slug,
        "frontend_state": "",
        "nonce": "nonce",
        "redirect_uri": "https://tenant.invalid/login/callback",
        "correlation_id": "corr-invalid",
        "exp": issue_time + 600,
        "iat": issue_time,
        "config_version": datetime.now(timezone.utc).isoformat(),
    }

    signed_state = jwt.encode(state_payload, dummy_settings.jwt_secret, algorithm="HS256")

    # Store state in Redis cache with correct key format (uses nonce, not full JWT)
    cache_payload = {
        "tenant_id": str(tenant_id),
        "tenant_slug": slug,
        "redirect_uri": state_payload["redirect_uri"],
        "config_version": state_payload["config_version"],
        "iat": state_payload["iat"],
    }
    await redis_client.setex(
        f"oidc:state:{state_payload['nonce']}",  # Use nonce, not full JWT
        dummy_settings.oidc_state_ttl_seconds,
        json.dumps(cache_payload),
    )

    fake_response = FakeResponse({"id_token": "id", "access_token": "token"})
    monkeypatch.setattr(
        federation_router,
        "aiohttp_client",
        lambda: FakeAioHttpClient(fake_response),
    )
    monkeypatch.setattr(federation_router, "PyJWKClient", FakeJWKClient)
    monkeypatch.setattr(federation_router, "JWKClient", FakeJWKClient)

    callback = CallbackRequest(code="auth-code", state=signed_state)

    with pytest.raises(HTTPException) as exc:
        await federation_router.auth_callback(callback, container=container)

    assert exc.value.status_code == 401
    # Accept either "invalid" or "failed to validate" in error message
    assert ("invalid" in exc.value.detail.lower() or "failed to validate" in exc.value.detail.lower())


# Tests for new error handling helper functions


def test_classify_http_error_502():
    """Test 502 Bad Gateway classification."""
    assert federation_router._classify_http_error(502) == "http_502_bad_gateway"


def test_classify_http_error_503():
    """Test 503 Service Unavailable classification."""
    assert federation_router._classify_http_error(503) == "http_503_service_unavailable"


def test_classify_http_error_504():
    """Test 504 Gateway Timeout classification."""
    assert federation_router._classify_http_error(504) == "http_504_gateway_timeout"


def test_classify_http_error_401():
    """Test 401 Unauthorized classification."""
    assert federation_router._classify_http_error(401) == "http_401_unauthorized"


def test_classify_http_error_403():
    """Test 403 Forbidden classification."""
    assert federation_router._classify_http_error(403) == "http_403_forbidden"


def test_classify_http_error_429():
    """Test 429 Rate Limited classification."""
    assert federation_router._classify_http_error(429) == "http_429_rate_limited"


def test_classify_http_error_4xx():
    """Test generic 4xx classification."""
    assert federation_router._classify_http_error(404) == "http_4xx_client_error"
    assert federation_router._classify_http_error(422) == "http_4xx_client_error"


def test_classify_http_error_5xx():
    """Test generic 5xx classification."""
    assert federation_router._classify_http_error(500) == "http_5xx_server_error"
    assert federation_router._classify_http_error(599) == "http_5xx_server_error"


def test_classify_http_error_unknown():
    """Test unknown status codes."""
    assert federation_router._classify_http_error(200) == "http_unknown"
    assert federation_router._classify_http_error(999) == "http_unknown"


def test_is_proxy_error_502_with_html():
    """Test proxy detection for 502 with HTML content-type."""
    headers = {"content-type": "text/html", "server": "nginx"}
    assert federation_router._is_proxy_error(502, headers) is True


def test_is_proxy_error_502_with_json():
    """Test proxy detection for 502 with JSON content-type (IdP app error)."""
    headers = {"content-type": "application/json"}
    assert federation_router._is_proxy_error(502, headers) is False


def test_is_proxy_error_503_with_nginx():
    """Test proxy detection for 503 with nginx server header."""
    headers = {"server": "nginx/1.18"}
    assert federation_router._is_proxy_error(503, headers) is True


def test_is_proxy_error_503_with_apache():
    """Test proxy detection for 503 with Apache server header."""
    headers = {"server": "Apache/2.4"}
    assert federation_router._is_proxy_error(503, headers) is True


def test_is_proxy_error_non_gateway_error():
    """Test proxy detection returns False for non-gateway errors."""
    headers = {"content-type": "text/html"}
    assert federation_router._is_proxy_error(401, headers) is False
    assert federation_router._is_proxy_error(500, headers) is False


def test_classify_token_error_invalid_grant():
    """Test OAuth invalid_grant classification."""
    assert federation_router._classify_token_error(400, "invalid_grant") == "oauth_invalid_grant"


def test_classify_token_error_invalid_client():
    """Test OAuth invalid_client classification."""
    assert federation_router._classify_token_error(401, "invalid_client") == "oauth_invalid_client"


def test_classify_token_error_access_denied():
    """Test OAuth access_denied classification."""
    assert federation_router._classify_token_error(403, "access_denied") == "oauth_access_denied"


def test_classify_token_error_unauthorized_client():
    """Test OAuth unauthorized_client classification."""
    assert federation_router._classify_token_error(401, "unauthorized_client") == "oauth_unauthorized_client"


def test_classify_token_error_fallback_to_http():
    """Test fallback to HTTP classification for unknown OAuth errors."""
    assert federation_router._classify_token_error(502, "unknown_error") == "http_502_bad_gateway"
    assert federation_router._classify_token_error(401, "") == "http_401_unauthorized"


def test_redact_sensitive_data():
    """Test sensitive data redaction."""
    data = {
        "client_secret": "secret123",
        "access_token": "token456",
        "username": "testuser",
        "grant_type": "authorization_code",
    }
    redacted = federation_router._redact_sensitive_data(data)

    assert redacted["client_secret"] == "***REDACTED***"
    assert redacted["access_token"] == "***REDACTED***"
    assert redacted["username"] == "testuser"  # Not sensitive
    assert redacted["grant_type"] == "authorization_code"  # Not sensitive


def test_redact_sensitive_data_id_token():
    """Test ID token and refresh token redaction."""
    data = {
        "id_token": "eyJhbGc...",
        "refresh_token": "refresh123",
        "user_id": "123",
    }
    redacted = federation_router._redact_sensitive_data(data)

    assert redacted["id_token"] == "***REDACTED***"
    assert redacted["refresh_token"] == "***REDACTED***"
    assert redacted["user_id"] == "123"


def test_safe_headers():
    """Test sensitive headers removal."""
    headers = {
        "authorization": "Bearer token123",
        "content-type": "application/json",
        "server": "nginx",
        "set-cookie": "session=abc",
        "x-custom": "value",
    }
    safe = federation_router._safe_headers(headers)

    assert "authorization" not in safe
    assert "set-cookie" not in safe
    assert safe["content-type"] == "application/json"
    assert safe["server"] == "nginx"
    assert safe["x-custom"] == "value"


def test_safe_headers_proxy_authorization():
    """Test proxy-authorization header removal."""
    headers = {
        "proxy-authorization": "Basic token123",
        "via": "1.1 proxy",
    }
    safe = federation_router._safe_headers(headers)

    assert "proxy-authorization" not in safe
    assert safe["via"] == "1.1 proxy"
