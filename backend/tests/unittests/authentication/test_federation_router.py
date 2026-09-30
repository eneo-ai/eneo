"""Unit tests for OIDC federation router edge cases."""

import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException

from eneo.authentication import federation_router
from eneo.authentication.federation_router import CallbackRequest
from eneo.settings.encryption_service import EncryptionService
from eneo.tenants.tenant import TenantInDB, TenantState
from eneo.users.user import UserInDB
from eneo.users.user_service import UserService


class DummySettings(SimpleNamespace):
    def __init__(self, **overrides):
        defaults = {
            "jwt_secret": "unit-test-secret-padded-to-the-hs256-minimum",
            "oidc_state_ttl_seconds": 600,
            "oidc_redirect_grace_period_seconds": 900,
            "strict_oidc_redirect_validation": True,
            "tenant_credentials_enabled": False,
            "federation_enabled": False,
            "public_origin": "https://global.example.com",
            "openai_api_key": None,
            "anthropic_api_key": None,
            "azure_api_key": None,
            "mistral_api_key": None,
            "ovhcloud_api_key": None,
            "vllm_api_key": None,
            "oidc_discovery_endpoint": None,
            "oidc_client_secret": None,
            "oidc_client_id": None,
            "oidc_tenant_id": None,
            "oidc_allowed_domains": [],
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
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return json.dumps(self._payload)


class FakeAioHttpClient:
    def __init__(self, response: FakeResponse):
        self._response = response

    def get(self, *args, **kwargs):  # noqa: ARG002
        return self._response

    def post(self, *args, **kwargs):  # noqa: ARG002
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

    async def get_all_active(self):
        if self._tenant.state == TenantState.ACTIVE:
            return [self._tenant]
        return []


class UserRepoStub:
    def __init__(self, user: UserInDB):
        self._user = user

    async def has_removed_user_by_email(self, email: str, tenant_id) -> bool:
        return False

    async def get_user_by_email(self, email: str):
        if email.lower() == self._user.email.lower():
            return self._user
        return None


class AuthServiceStub:
    def __init__(self, claims: dict[str, object] | None = None):
        self.claims = (
            claims
            if claims is not None
            else {"sub": "subject", "email": "user@Example.COM", "email_verified": True}
        )

    def get_payload_from_openid_jwt(self, **kwargs):  # noqa: ARG002
        return self.claims

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
    def __init__(
        self,
        *,
        tenant_repo,
        user_repo,
        auth_service,
        redis_client,
        encryption_service,
    ):
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

    def user_service(self):
        return UserService(
            user_repo=self._user_repo,
            tenant_repo=self._tenant_repo,
            auth_service=self._auth_service,
            audit_service=getattr(self, "_audit_service", None),
            api_key_auth_resolver=None,
            api_key_v2_repo=None,
            settings_repo=None,
            info_blob_repo=None,
        )


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
        await federation_router.initiate_auth(
            tenant="suspended", state=None, container=container
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_initiate_auth_uses_additional_redirect_uri_from_query_param(monkeypatch):
    tenant = TenantInDB(
        id=uuid4(),
        name="AdditionalRedirectTenant",
        display_name="AdditionalRedirectTenant",
        quota_limit=1024**3,
        slug="additional-redirect-tenant",
        state=TenantState.ACTIVE,
        modules=[],
        api_credentials={},
        federation_config={
            "provider": "entra",
            "client_id": "client",
            "client_secret": "secret",
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
            "jwks_uri": "https://idp.example.com/jwks",
            "discovery_endpoint": "https://idp.example.com/.well-known/openid-configuration",
            "canonical_public_origin": "https://canonical.example.com",
            "redirect_path": "/auth/callback",
            "additional_redirect_uris": ["https://external.example.com/auth/callback"],
            "allowed_domains": ["example.com"],
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    dummy_settings = DummySettings(federation_enabled=True)
    monkeypatch.setattr(federation_router, "get_settings", lambda: dummy_settings)

    container = MockContainer(
        tenant_repo=TenantRepoStub(tenant),
        user_repo=None,
        auth_service=None,
        redis_client=FakeRedis(),
        encryption_service=EncryptionService(None),
    )

    response = await federation_router.initiate_auth(
        tenant=tenant.slug,
        state=None,
        redirect_uri_param="https://external.example.com/auth/callback",
        container=container,
    )

    query = parse_qs(urlparse(response.authorization_url).query)
    assert query["redirect_uri"] == ["https://external.example.com/auth/callback"]


@pytest.mark.asyncio
async def test_initiate_auth_single_tenant_accepts_db_redirect_uri(monkeypatch):
    tenant = TenantInDB(
        id=uuid4(),
        name="SingleTenant",
        display_name="SingleTenant",
        quota_limit=1024**3,
        slug="single-tenant",
        state=TenantState.ACTIVE,
        modules=[],
        api_credentials={},
        federation_config={
            "additional_redirect_uris": ["https://external.example.com/auth/callback"]
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    dummy_settings = DummySettings(
        federation_enabled=False,
        oidc_discovery_endpoint="https://idp.example.com/.well-known/openid-configuration",
        oidc_client_id="client",
        oidc_client_secret="secret",
        public_origin="https://canonical.example.com",
    )
    monkeypatch.setattr(federation_router, "get_settings", lambda: dummy_settings)
    monkeypatch.setattr(
        federation_router,
        "aiohttp_client",
        lambda: FakeAioHttpClient(
            FakeResponse(
                {"authorization_endpoint": "https://idp.example.com/authorize"}
            )
        ),
    )

    container = MockContainer(
        tenant_repo=TenantRepoStub(tenant),
        user_repo=None,
        auth_service=None,
        redis_client=FakeRedis(),
        encryption_service=EncryptionService(None),
    )

    response = await federation_router.initiate_auth(
        tenant=None,
        state=None,
        redirect_uri_param="https://external.example.com/auth/callback",
        container=container,
    )

    query = parse_qs(urlparse(response.authorization_url).query)
    assert query["redirect_uri"] == ["https://external.example.com/auth/callback"]


@pytest.mark.asyncio
async def test_initiate_auth_rejects_unregistered_redirect_uri(monkeypatch):
    tenant = TenantInDB(
        id=uuid4(),
        name="RejectRedirectTenant",
        display_name="RejectRedirectTenant",
        quota_limit=1024**3,
        slug="reject-redirect-tenant",
        state=TenantState.ACTIVE,
        modules=[],
        api_credentials={},
        federation_config={
            "provider": "entra",
            "client_id": "client",
            "client_secret": "secret",
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
            "jwks_uri": "https://idp.example.com/jwks",
            "discovery_endpoint": "https://idp.example.com/.well-known/openid-configuration",
            "canonical_public_origin": "https://canonical.example.com",
            "redirect_path": "/auth/callback",
            "additional_redirect_uris": ["https://external.example.com/auth/callback"],
            "allowed_domains": ["example.com"],
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    dummy_settings = DummySettings(federation_enabled=True)
    monkeypatch.setattr(federation_router, "get_settings", lambda: dummy_settings)

    container = MockContainer(
        tenant_repo=TenantRepoStub(tenant),
        user_repo=None,
        auth_service=None,
        redis_client=FakeRedis(),
        encryption_service=EncryptionService(None),
    )

    with pytest.raises(HTTPException) as exc:
        await federation_router.initiate_auth(
            tenant=tenant.slug,
            state=None,
            redirect_uri_param="https://evil.example.com/auth/callback",
            container=container,
        )

    assert exc.value.status_code == 400
    assert "not registered" in exc.value.detail


@pytest.mark.asyncio
async def test_auth_callback_accepts_recent_redirect_change(monkeypatch):
    dummy_settings = DummySettings(federation_enabled=True)
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
        "frontend_state": '{"loginMethod":"oidc","next":"/module-login?state=a%2526b"}',
        "nonce": "nonce",
        "redirect_uri": "https://old.tenant.example.com/login/callback",
        "correlation_id": "corr-123",
        "exp": issue_time + 600,
        "iat": issue_time,
        "config_version": old_version,
    }

    signed_state = jwt.encode(
        state_payload, dummy_settings.jwt_secret, algorithm="HS256"
    )

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
    tenant.federation_config["canonical_public_origin"] = (
        "https://new.tenant.example.com"
    )
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

    assert result == {
        "access_token": "access-token",
        "frontend_state": state_payload["frontend_state"],
    }
    assert redis_client._store == {}


@pytest.mark.asyncio
async def test_auth_callback_accepts_additional_redirect_uri(monkeypatch):
    dummy_settings = DummySettings(
        federation_enabled=True,
        oidc_redirect_grace_period_seconds=0,
        strict_oidc_redirect_validation=True,
    )
    monkeypatch.setattr(federation_router, "get_settings", lambda: dummy_settings)

    redis_client = FakeRedis()
    tenant_id = uuid4()
    slug = "tenant-additional-redirect"

    tenant = TenantInDB(
        id=tenant_id,
        name="Tenant Additional Redirect",
        display_name="Tenant Additional Redirect",
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
            "canonical_public_origin": "https://canonical.tenant.example.com",
            "redirect_path": "/auth/callback",
            "additional_redirect_uris": [
                "https://alt.tenant.example.com/auth/callback"
            ],
            "allowed_domains": ["example.com"],
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
    config_version = datetime.now(timezone.utc).isoformat()
    state_payload = {
        "tenant_id": str(tenant_id),
        "tenant_slug": slug,
        "frontend_state": "",
        "nonce": "nonce-additional-redirect",
        "redirect_uri": "https://alt.tenant.example.com/auth/callback",
        "correlation_id": "corr-additional-redirect",
        "exp": issue_time + 600,
        "iat": issue_time,
        "config_version": config_version,
    }

    signed_state = jwt.encode(
        state_payload, dummy_settings.jwt_secret, algorithm="HS256"
    )

    cache_payload = {
        "tenant_id": str(tenant_id),
        "tenant_slug": slug,
        "redirect_uri": state_payload["redirect_uri"],
        "config_version": config_version,
        "iat": state_payload["iat"],
    }
    await redis_client.setex(
        f"oidc:state:{state_payload['nonce']}",
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
    result = await federation_router.auth_callback(callback, container=container)

    assert result == {"access_token": "access-token", "frontend_state": ""}
    assert redis_client._store == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_email", ["@example.com", "user@@example.com"])
async def test_auth_callback_rejects_invalid_email_format(monkeypatch, bad_email):
    dummy_settings = DummySettings(federation_enabled=True)
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

    signed_state = jwt.encode(
        state_payload, dummy_settings.jwt_secret, algorithm="HS256"
    )

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
    assert (
        "invalid" in exc.value.detail.lower()
        or "failed to validate" in exc.value.detail.lower()
    )


# --- JIT Provisioning Tests ---


class UserRepoStubForJIT:
    """User repo stub that can simulate a user not existing initially, then being created."""

    def __init__(
        self, existing_user: UserInDB | None = None, tenant: TenantInDB | None = None
    ):
        self._user = existing_user
        self._tenant = tenant
        self._created_user = None

    async def has_removed_user_by_email(self, email: str, tenant_id) -> bool:
        return bool(
            self._user
            and self._user.tenant_id == tenant_id
            and self._user.email.lower() == email.lower()
            and self._user.deleted_at is not None
        )

    async def get_user_by_email(self, email: str):
        if (
            self._user
            and self._user.deleted_at is None
            and email.lower() == self._user.email.lower()
        ):
            return self._user
        if self._created_user and email.lower() == self._created_user.email.lower():
            return self._created_user
        return None

    async def get_user_by_username(self, username: str, with_deleted: bool = False):
        for user in (self._user, self._created_user):
            if user is not None and user.username == username:
                return user
        return None

    async def add(self, user_add):
        # Create a fake UserInDB from the UserAdd
        self._created_user = UserInDB(
            id=uuid4(),
            username=user_add.username,
            email=user_add.email,
            salt=None,
            password=None,
            used_tokens=0,
            tenant_id=user_add.tenant_id,
            tenant=self._tenant,
            quota_limit=1024**3,
            user_groups=[],
            roles=[],
            state=user_add.state.value,
        )
        return self._created_user


class AuditServiceStub:
    def __init__(self):
        self.logged_events = []

    async def log(self, **kwargs):
        self.logged_events.append(kwargs)
        return None


class MockContainerForJIT:
    def __init__(
        self,
        *,
        tenant_repo,
        user_repo,
        auth_service,
        redis_client,
        encryption_service,
        audit_service=None,
        allowed_origin_repo=None,
    ):
        self._tenant_repo = tenant_repo
        self._user_repo = user_repo
        self._auth_service = auth_service
        self._redis_client = redis_client
        self._encryption_service = encryption_service
        self._audit_service = audit_service
        self._allowed_origin_repo = allowed_origin_repo

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

    def user_service(self):
        return UserService(
            user_repo=self._user_repo,
            tenant_repo=self._tenant_repo,
            auth_service=self._auth_service,
            audit_service=getattr(self, "_audit_service", None),
            api_key_auth_resolver=None,
            api_key_v2_repo=None,
            settings_repo=None,
            info_blob_repo=None,
        )

    def audit_service(self):
        return self._audit_service

    def allowed_origin_repo(self):
        return self._allowed_origin_repo


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "admission_case",
    [
        "allowed",
        "empty-domains",
        "wrong-domain",
        "unverified",
        "missing-verification",
        "mapped-unverified",
        "jit-disabled",
        "removed",
        "inactive",
    ],
)
async def test_callback_enforces_jit_admission(monkeypatch, admission_case):
    """The callback only creates users that meet the complete admission policy."""
    dummy_settings = DummySettings(federation_enabled=True)
    monkeypatch.setattr(federation_router, "get_settings", lambda: dummy_settings)

    redis_client = FakeRedis()
    tenant_id = uuid4()
    slug = "tenant-jit"
    default_role_id = uuid4()

    # Tenant with provisioning enabled and default role set
    tenant = TenantInDB(
        id=tenant_id,
        name="Tenant JIT",
        display_name="Tenant JIT",
        slug=slug,
        quota_limit=1024**3,
        state=TenantState.ACTIVE,
        provisioning=True,  # JIT provisioning enabled
        default_role_id=default_role_id,
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
            "canonical_public_origin": "https://tenant.jit.example.com",
            "redirect_path": "/login/callback",
            "allowed_domains": ["example.com"],
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    claims: dict[str, object] = {
        "sub": "subject",
        "email": "user@example.com",
        "email_verified": True,
    }
    existing = None
    if admission_case == "empty-domains":
        tenant.federation_config["allowed_domains"] = []
    elif admission_case == "wrong-domain":
        tenant.federation_config["allowed_domains"] = ["outside.example"]
    elif admission_case == "unverified":
        claims["email_verified"] = False
    elif admission_case == "missing-verification":
        claims.pop("email_verified")
    elif admission_case == "mapped-unverified":
        tenant.federation_config["claims_mapping"] = {"email": "mail"}
        claims["mail"] = "another@example.com"
    elif admission_case == "jit-disabled":
        tenant.provisioning = False
    elif admission_case in ("removed", "inactive"):
        existing = UserInDB(
            id=uuid4(),
            email="user@example.com",
            username="user",
            tenant=tenant,
            tenant_id=tenant.id,
            state="deleted" if admission_case == "removed" else "inactive",
            deleted_at=datetime.now(timezone.utc)
            if admission_case == "removed"
            else None,
        )

    user_repo = UserRepoStubForJIT(existing_user=existing, tenant=tenant)
    audit_service = AuditServiceStub()

    container = MockContainerForJIT(
        tenant_repo=TenantRepoStub(tenant),
        user_repo=user_repo,
        auth_service=AuthServiceStub(claims),
        redis_client=redis_client,
        encryption_service=EncryptionService(None),
        audit_service=audit_service,
    )

    issue_time = int(time.time())
    config_version = datetime.now(timezone.utc).isoformat()
    state_payload = {
        "tenant_id": str(tenant_id),
        "tenant_slug": slug,
        "frontend_state": "",
        "nonce": "nonce-jit",
        "redirect_uri": "https://tenant.jit.example.com/login/callback",
        "correlation_id": "corr-jit",
        "exp": issue_time + 600,
        "iat": issue_time,
        "config_version": config_version,
    }

    signed_state = jwt.encode(
        state_payload, dummy_settings.jwt_secret, algorithm="HS256"
    )

    cache_payload = {
        "tenant_id": str(tenant_id),
        "tenant_slug": slug,
        "redirect_uri": state_payload["redirect_uri"],
        "config_version": config_version,
        "iat": state_payload["iat"],
    }
    await redis_client.setex(
        f"oidc:state:{state_payload['nonce']}",
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

    if admission_case != "allowed":
        with pytest.raises(HTTPException) as caught:
            await federation_router.auth_callback(callback, container=container)
        assert caught.value.status_code == 403
        assert caught.value.headers["X-Correlation-ID"] == "corr-jit"
        assert user_repo._created_user is None
        assert audit_service.logged_events == []
        assert await redis_client.get("oidc:state:nonce-jit") is None
        return

    result = await federation_router.auth_callback(callback, container=container)

    # Verify login succeeded
    assert result == {"access_token": "access-token", "frontend_state": ""}

    # Verify user was created in the correct tenant
    assert user_repo._created_user is not None
    # Email is normalized to lowercase when stored
    assert user_repo._created_user.email == "user@example.com"
    assert user_repo._created_user.username == "user"
    # CRITICAL: Verify user is created in the correct tenant (from state)
    assert user_repo._created_user.tenant_id == tenant_id

    # Verify audit event was logged for the correct tenant
    assert len(audit_service.logged_events) == 1
    audit_event = audit_service.logged_events[0]
    assert audit_event["metadata"]["provisioning_method"] == "jit_federation"
    assert audit_event["tenant_id"] == tenant_id


@pytest.mark.asyncio
async def test_jit_provisioning_does_not_reuse_a_taken_username():
    """Two accounts must never share a username: when the email local part is
    already in use, the new account is named by its full email instead."""
    tenant = TenantInDB(
        id=uuid4(),
        name="Tenant JIT",
        display_name="Tenant JIT",
        slug="tenant-jit-username",
        quota_limit=1024**3,
        state=TenantState.ACTIVE,
        provisioning=True,
        default_role_id=None,
        modules=[],
        api_credentials={},
        federation_config={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    existing = UserInDB(
        id=uuid4(),
        username="anna.svensson",
        email="anna.svensson@sundsvall.se",
        salt=None,
        password=None,
        used_tokens=0,
        tenant_id=uuid4(),
        tenant=tenant,
        quota_limit=1024**3,
        user_groups=[],
        roles=[],
        state="active",
    )
    container = MockContainerForJIT(
        tenant_repo=TenantRepoStub(tenant),
        user_repo=UserRepoStubForJIT(existing_user=existing, tenant=tenant),
        auth_service=AuthServiceStub(),
        redis_client=FakeRedis(),
        encryption_service=EncryptionService(None),
    )

    from eneo.authentication.auth_models import FederatedIdentity

    created, was_created = await container.user_service().resolve_federated_user(
        identity=FederatedIdentity(email="anna.svensson@ange.se", email_verified=True),
        tenant_id=tenant.id,
        allowed_domains=["ange.se"],
        correlation_id="corr-jit-username",
    )

    assert was_created is True

    assert created.email == "anna.svensson@ange.se"
    assert created.username == "anna.svensson@ange.se"
    assert created.username != existing.username


@pytest.mark.asyncio
async def test_jit_provisioning_returns_403_when_disabled(monkeypatch):
    """Test that login fails with 403 when JIT provisioning is disabled and user doesn't exist."""
    dummy_settings = DummySettings(federation_enabled=True)
    monkeypatch.setattr(federation_router, "get_settings", lambda: dummy_settings)

    redis_client = FakeRedis()
    tenant_id = uuid4()
    slug = "tenant-no-jit"

    # Tenant with provisioning disabled
    tenant = TenantInDB(
        id=tenant_id,
        name="Tenant No JIT",
        display_name="Tenant No JIT",
        slug=slug,
        quota_limit=1024**3,
        state=TenantState.ACTIVE,
        provisioning=False,  # JIT provisioning disabled
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
            "canonical_public_origin": "https://tenant.nojit.example.com",
            "redirect_path": "/login/callback",
            "allowed_domains": ["example.com"],
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    # User repo that returns None (user doesn't exist)
    user_repo = UserRepoStubForJIT(existing_user=None)

    container = MockContainerForJIT(
        tenant_repo=TenantRepoStub(tenant),
        user_repo=user_repo,
        auth_service=AuthServiceStub(),
        redis_client=redis_client,
        encryption_service=EncryptionService(None),
        audit_service=None,
    )

    issue_time = int(time.time())
    config_version = datetime.now(timezone.utc).isoformat()
    state_payload = {
        "tenant_id": str(tenant_id),
        "tenant_slug": slug,
        "frontend_state": "",
        "nonce": "nonce-no-jit",
        "redirect_uri": "https://tenant.nojit.example.com/login/callback",
        "correlation_id": "corr-no-jit",
        "exp": issue_time + 600,
        "iat": issue_time,
        "config_version": config_version,
    }

    signed_state = jwt.encode(
        state_payload, dummy_settings.jwt_secret, algorithm="HS256"
    )

    cache_payload = {
        "tenant_id": str(tenant_id),
        "tenant_slug": slug,
        "redirect_uri": state_payload["redirect_uri"],
        "config_version": config_version,
        "iat": state_payload["iat"],
    }
    await redis_client.setex(
        f"oidc:state:{state_payload['nonce']}",
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

    assert exc.value.status_code == 403
    assert "User not found" in exc.value.detail

    # Verify no user was created
    assert user_repo._created_user is None


@pytest.mark.asyncio
async def test_auth_callback_rejects_malformed_state_redirect_uri(monkeypatch):
    dummy_settings = DummySettings(
        federation_enabled=True,
        oidc_redirect_grace_period_seconds=0,
        strict_oidc_redirect_validation=True,
    )
    monkeypatch.setattr(federation_router, "get_settings", lambda: dummy_settings)

    redis_client = FakeRedis()
    tenant_id = uuid4()
    slug = "tenant-malformed-redirect"

    tenant = TenantInDB(
        id=tenant_id,
        name="Tenant Malformed Redirect",
        display_name="Tenant Malformed Redirect",
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
            "canonical_public_origin": "https://canonical.tenant.example.com",
            "redirect_path": "/auth/callback",
            "additional_redirect_uris": [
                "https://alt.tenant.example.com/auth/callback"
            ],
            "allowed_domains": ["example.com"],
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
    config_version = datetime.now(timezone.utc).isoformat()
    state_payload = {
        "tenant_id": str(tenant_id),
        "tenant_slug": slug,
        "frontend_state": "",
        "nonce": "nonce-malformed-redirect",
        "redirect_uri": "https://alt.tenant.example.com/auth/callback?x=1",
        "correlation_id": "corr-malformed-redirect",
        "exp": issue_time + 600,
        "iat": issue_time,
        "config_version": config_version,
    }

    signed_state = jwt.encode(
        state_payload, dummy_settings.jwt_secret, algorithm="HS256"
    )

    cache_payload = {
        "tenant_id": str(tenant_id),
        "tenant_slug": slug,
        "redirect_uri": state_payload["redirect_uri"],
        "config_version": config_version,
        "iat": state_payload["iat"],
    }
    await redis_client.setex(
        f"oidc:state:{state_payload['nonce']}",
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

    assert exc.value.status_code == 400
    assert "Redirect URI mismatch" in exc.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "admission_case",
    [
        "allowed",
        "jit-disabled",
        "empty-domains",
        "missing-verification",
        "removed",
        "existing-scim",
    ],
)
async def test_global_oidc_endpoint_uses_shared_admission(monkeypatch, admission_case):
    from starlette.requests import Request

    from eneo.authentication.auth_models import OpenIdConnectLogin
    from eneo.users import user_router, user_service

    tenant = TenantInDB(
        id=uuid4(),
        name="OIDC tenant",
        state=TenantState.ACTIVE,
        quota_limit=1024**3,
        provisioning=admission_case != "jit-disabled",
    )
    settings = DummySettings(
        oidc_discovery_endpoint="https://idp.example.com/discovery",
        oidc_client_id="client",
        oidc_client_secret="secret",
        oidc_tenant_id=str(tenant.id),
        oidc_allowed_domains=[]
        if admission_case in ("empty-domains", "existing-scim")
        else ["example.com"],
    )
    claims: dict[str, object] = {"sub": "subject", "email": "user@example.com"}
    if admission_case not in ("missing-verification", "existing-scim"):
        claims["email_verified"] = True
    existing = None
    if admission_case in ("removed", "existing-scim"):
        existing = UserInDB(
            id=uuid4(),
            email="user@example.com",
            username="user",
            tenant=tenant,
            tenant_id=tenant.id,
            state="deleted" if admission_case == "removed" else "active",
            deleted_at=datetime.now(timezone.utc)
            if admission_case == "removed"
            else None,
        )
    if admission_case == "existing-scim":
        tenant.provisioning = False
    repository = UserRepoStubForJIT(existing_user=existing, tenant=tenant)
    container = MockContainerForJIT(
        tenant_repo=TenantRepoStub(tenant),
        user_repo=repository,
        auth_service=AuthServiceStub(claims),
        redis_client=FakeRedis(),
        encryption_service=EncryptionService(None),
    )
    monkeypatch.setattr(user_router.config, "get_settings", lambda: settings)
    monkeypatch.setattr(user_service, "get_settings", lambda: settings)
    response = FakeResponse(
        {
            "token_endpoint": "https://idp.example.com/token",
            "jwks_uri": "https://idp.example.com/jwks",
            "id_token_signing_alg_values_supported": ["RS256"],
            "id_token": "id",
            "access_token": "token",
        }
    )
    monkeypatch.setattr(
        user_router, "aiohttp_client", lambda: FakeAioHttpClient(response)
    )
    monkeypatch.setattr(user_router.jwt, "PyJWKClient", FakeJWKClient)
    login = OpenIdConnectLogin(
        code="code",
        code_verifier="verifier",
        client_id="client",
        redirect_uri="https://global.example.com/login/callback",
    )
    request = Request({"type": "http", "headers": []})
    # The existing token exchange uses aiohttp.BasicAuth; explicitly capture
    # its deprecation while exercising the account decision through the route.
    with pytest.warns(DeprecationWarning, match="BasicAuth is deprecated"):
        if admission_case in ("allowed", "existing-scim"):
            token = await user_router.login_with_mobilityguard(
                request, login, container
            )
            assert token.access_token == "access-token"
            assert (repository._created_user is not None) is (
                admission_case == "allowed"
            )
        else:
            with pytest.raises(HTTPException) as caught:
                await user_router.login_with_mobilityguard(request, login, container)
            assert caught.value.status_code == 403
            assert caught.value.headers["X-Correlation-ID"]
            assert repository._created_user is None
