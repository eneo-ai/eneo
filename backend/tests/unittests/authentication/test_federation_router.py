"""Unit tests for OIDC federation router edge cases."""

import asyncio
import json
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import cast
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from eneo.audit.domain.action_types import ActionType
from eneo.authentication import federation_router
from eneo.authentication.auth_models import FederatedIdentity
from eneo.authentication.federation_router import CallbackRequest
from eneo.authentication.oidc.errors import (
    OidcLoginUnavailableError,
    OidcTransactionInvalidError,
)
from eneo.authentication.oidc.transaction import (
    OidcChannel,
    OidcTransaction,
    code_challenge,
    save_transaction,
)
from eneo.server.endpoint_routes import endpoint_routes
from eneo.server.exception_handlers import add_exception_handlers
from eneo.server.middleware.request_context import RequestContextMiddleware
from eneo.settings.encryption_service import EncryptionService
from eneo.tenants.tenant import TenantInDB, TenantState
from eneo.users.user import UserInDB
from eneo.users.user_service import UserService
from tests.fake_oidc_provider import DROP, FakeOidcProvider, install
from tests.identity_bindings_in_memory import IdentityBindingsInMemory


class DummySettings(SimpleNamespace):
    def __init__(self, **overrides):
        defaults = {
            "jwt_secret": "unit-test-secret-padded-to-the-hs256-minimum",
            "oidc_state_ttl_seconds": 600,
            "oidc_jwks_cache_ttl_seconds": 3600,
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

    async def getdel(self, key: str) -> str | None:
        return self._store.pop(key, None)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


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

    async def get_users_by_email(self, email: str, *, limit: int):
        user = await self.get_user_by_email(email)
        return [user] if user else []

    async def get_user_by_id(self, id, with_deleted: bool = False):
        if id == self._user.id and (with_deleted or self._user.deleted_at is None):
            return self._user
        return None

    async def get_user_by_id_for_update(self, id):
        return await self.get_user_by_id(id)


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


class _SessionsHandBack:
    """The callback route starts a browser session for the token it hands
    out; these tests check the sign-in, so the token comes back unchanged."""

    async def start(self, access_token: str) -> str:
        return access_token


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
        self._identity_bindings = IdentityBindingsInMemory()

    def browser_session_service(self):
        return _SessionsHandBack()

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
            identity_binding_repo=self._identity_bindings,
        )


PROVIDER_ISSUER = "https://idp.example.com"


@pytest.fixture(autouse=True)
def provider(monkeypatch) -> FakeOidcProvider:
    """The organisations' provider: discovery, keys and the token endpoint."""
    fake = FakeOidcProvider(
        issuer=PROVIDER_ISSUER, client_id="client", client_secret="secret"
    )
    install(monkeypatch, fake)
    return fake


async def _signed_callback(
    redis_client: FakeRedis,
    provider: FakeOidcProvider,
    *,
    tenant: TenantInDB,
    redirect_uri: str,
    frontend_state: str = "",
    correlation_id: str = "corr",
    config_version: str | None = None,
    claims: dict[str, object] | None = None,
    channel: OidcChannel = "api",
    binding_challenge: str | None = None,
) -> CallbackRequest:
    """A callback for a sign-in started at the tenant, as initiate stores it.

    With ``claims`` the provider sends exactly those email facts (no
    email_verified unless given); without, its defaults.
    """
    transaction = OidcTransaction.start(
        "login",
        channel=channel,
        binding_challenge=binding_challenge,
        redirect_uri=redirect_uri,
        tenant_id=str(tenant.id),
        tenant_slug=cast(str, tenant.slug),
        config_version=config_version,
        issuer=provider.issuer,
        iss_parameter_supported=provider.advertise_iss_parameter,
    )
    await save_transaction(redis_client, transaction, ttl_seconds=600)
    state = jwt.encode(
        {
            "tenant_id": transaction.tenant_id,
            "tenant_slug": transaction.tenant_slug,
            "frontend_state": frontend_state,
            "transaction_id": transaction.id,
            "correlation_id": correlation_id,
            "exp": transaction.issued_at + 600,
            "iat": transaction.issued_at,
        },
        DummySettings().jwt_secret,
        algorithm="HS256",
    )
    code = provider.issue_code(
        client_id="client",
        redirect_uri=redirect_uri,
        nonce=transaction.nonce,
        **({"email_verified": DROP, **claims} if claims is not None else {}),
    )
    return CallbackRequest(code=code, state=state)


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
            response=Response(), tenant="suspended", state=None, container=container
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
        response=Response(),
        tenant=tenant.slug,
        state=None,
        redirect_uri_param="https://external.example.com/auth/callback",
        container=container,
    )

    query = parse_qs(urlparse(response.authorization_url).query)
    assert query["redirect_uri"] == ["https://external.example.com/auth/callback"]


def test_initiate_auth_keeps_the_request_correlation_id(monkeypatch):
    """Without a span the caller's X-Correlation-ID is the request's id: it
    names the login in the context, the response header and the state."""
    tenant = TenantInDB(
        id=uuid4(),
        name="CorrelatedTenant",
        display_name="CorrelatedTenant",
        quota_limit=1024**3,
        slug="correlated-tenant",
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
            "allowed_domains": ["example.com"],
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    dummy_settings = DummySettings(federation_enabled=True)
    monkeypatch.setattr(federation_router, "get_settings", lambda: dummy_settings)
    monkeypatch.setattr(
        "eneo.server.middleware.request_context._current_trace_id", lambda: None
    )
    container = MockContainer(
        tenant_repo=TenantRepoStub(tenant),
        user_repo=None,
        auth_service=None,
        redis_client=FakeRedis(),
        encryption_service=EncryptionService(None),
    )
    seen: dict[str, object] = {}
    real_ensure = federation_router.ensure_correlation_id

    def ensure_and_record() -> str:
        seen["correlation_id"] = real_ensure()
        return cast(str, seen["correlation_id"])

    monkeypatch.setattr(federation_router, "ensure_correlation_id", ensure_and_record)

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.include_router(federation_router.router)
    route = next(
        route for route in endpoint_routes(app.routes) if route.path == "/auth/initiate"
    )
    assert route.dependant is not None
    dependency = next(
        dependency
        for dependency in route.dependant.dependencies
        if dependency.name == "container"
    )
    app.dependency_overrides[dependency.call] = lambda: container

    response = TestClient(app).get(
        route.path,
        params={"tenant": tenant.slug},
        headers={"X-Correlation-ID": "abc"},
    )

    assert response.status_code == 200, response.text
    assert seen["correlation_id"] == "abc"
    assert response.headers["X-Correlation-ID"] == "abc"
    state = jwt.decode(
        response.json()["state"], dummy_settings.jwt_secret, algorithms=["HS256"]
    )
    assert state["correlation_id"] == "abc"


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

    container = MockContainer(
        tenant_repo=TenantRepoStub(tenant),
        user_repo=None,
        auth_service=None,
        redis_client=FakeRedis(),
        encryption_service=EncryptionService(None),
    )

    response = await federation_router.initiate_auth(
        response=Response(),
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
            response=Response(),
            tenant=tenant.slug,
            state=None,
            redirect_uri_param="https://evil.example.com/auth/callback",
            container=container,
        )

    assert exc.value.status_code == 400
    assert "not registered" in exc.value.detail


@pytest.mark.asyncio
async def test_auth_callback_accepts_recent_redirect_change(monkeypatch, provider):
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

    callback = await _signed_callback(
        redis_client,
        provider,
        tenant=tenant,
        redirect_uri="https://old.tenant.example.com/login/callback",
        frontend_state='{"loginMethod":"oidc","next":"/module-login?state=a%2526b"}',
        correlation_id="corr-123",
        config_version=old_version,
    )

    # Simulate canonical origin update during login
    tenant.federation_config["canonical_public_origin"] = (
        "https://new.tenant.example.com"
    )
    tenant.updated_at = datetime.now(timezone.utc)

    result = await federation_router.auth_callback(callback, container=container)

    assert result == {
        "access_token": "access-token",
        "frontend_state": '{"loginMethod":"oidc","next":"/module-login?state=a%2526b"}',
    }
    assert redis_client._store == {}


@pytest.mark.asyncio
async def test_auth_callback_accepts_additional_redirect_uri(monkeypatch, provider):
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

    callback = await _signed_callback(
        redis_client,
        provider,
        tenant=tenant,
        redirect_uri="https://alt.tenant.example.com/auth/callback",
        frontend_state="",
        correlation_id="corr-additional-redirect",
        config_version=datetime.now(timezone.utc).isoformat(),
    )
    result = await federation_router.auth_callback(callback, container=container)

    assert result == {"access_token": "access-token", "frontend_state": ""}
    assert redis_client._store == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_email", ["@example.com", "user@@example.com"])
async def test_auth_callback_rejects_invalid_email_format(
    monkeypatch, provider, bad_email
):
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
        auth_service=AuthServiceStub(),
        redis_client=redis_client,
        encryption_service=EncryptionService(None),
    )

    callback = await _signed_callback(
        redis_client,
        provider,
        tenant=tenant,
        redirect_uri="https://tenant.invalid/login/callback",
        frontend_state="",
        correlation_id="corr-invalid",
        config_version=datetime.now(timezone.utc).isoformat(),
        claims={"email": bad_email},
    )

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

    async def get_users_by_email(self, email: str, *, limit: int):
        user = await self.get_user_by_email(email)
        return [user] if user else []

    async def get_user_by_id(self, id, with_deleted: bool = False):
        for user in (self._user, self._created_user):
            if (
                user is not None
                and user.id == id
                and (with_deleted or user.deleted_at is None)
            ):
                return user
        return None

    async def get_user_by_id_for_update(self, id):
        return await self.get_user_by_id(id)

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
        # Sent to the worker: they outlive the sign-in's transaction.
        self.enqueued_events = []

    async def log(self, **kwargs):
        self.logged_events.append(kwargs)
        return None

    async def log_async(self, **kwargs):
        self.enqueued_events.append(kwargs)
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
        self._identity_bindings = IdentityBindingsInMemory()
        self._audit_service = audit_service
        self._allowed_origin_repo = allowed_origin_repo

    def browser_session_service(self):
        return _SessionsHandBack()

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
            identity_binding_repo=self._identity_bindings,
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
        "string-verification",
        "string-unverified",
        "entra-domain-verified",
        "entra-domain-unverified",
        "mapped-unverified",
        "jit-disabled",
        "removed",
        "inactive",
    ],
)
async def test_callback_enforces_jit_admission(monkeypatch, provider, admission_case):
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
    elif admission_case == "string-verification":
        claims["email_verified"] = "true"
    elif admission_case == "string-unverified":
        claims["email_verified"] = "false"
    elif admission_case == "entra-domain-verified":
        claims.pop("email_verified")
        claims["xms_edov"] = True
    elif admission_case == "entra-domain-unverified":
        claims.pop("email_verified")
        claims["xms_edov"] = False
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
        auth_service=AuthServiceStub(),
        redis_client=redis_client,
        encryption_service=EncryptionService(None),
        audit_service=audit_service,
    )

    callback = await _signed_callback(
        redis_client,
        provider,
        tenant=tenant,
        redirect_uri="https://tenant.jit.example.com/login/callback",
        frontend_state="",
        correlation_id="corr-jit",
        config_version=datetime.now(timezone.utc).isoformat(),
        claims=claims,
    )

    if admission_case not in (
        "allowed",
        "string-verification",
        "entra-domain-verified",
    ):
        with pytest.raises(HTTPException) as caught:
            await federation_router.auth_callback(callback, container=container)
        assert caught.value.status_code == (
            401 if admission_case == "unverified" else 403
        )
        assert caught.value.headers["X-Correlation-ID"] == "corr-jit"
        assert user_repo._created_user is None
        assert audit_service.logged_events == []
        assert redis_client._store == {}
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
    [audit_event] = [
        event
        for event in audit_service.logged_events
        if event["action"] == ActionType.USER_CREATED
    ]
    assert audit_event["metadata"]["provisioning_method"] == "jit_federation"
    assert audit_event["tenant_id"] == tenant_id
    # The new account is bound to the identity that created it.
    [bound] = [
        event
        for event in audit_service.logged_events
        if event["action"] == ActionType.IDENTITY_BOUND
    ]
    assert (bound["entity_id"], bound["metadata"]["method"]) == (
        user_repo._created_user.id,
        "jit",
    )


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

    created, was_created = await container.user_service().resolve_federated_user(
        identity=FederatedIdentity(
            issuer=PROVIDER_ISSUER,
            audience="client",
            subject="subject",
            email="anna.svensson@ange.se",
            email_verified=True,
        ),
        tenant_id=tenant.id,
        allowed_domains=["ange.se"],
        correlation_id="corr-jit-username",
    )

    assert was_created is True

    assert created.email == "anna.svensson@ange.se"
    assert created.username == "anna.svensson@ange.se"
    assert created.username != existing.username


@pytest.mark.asyncio
async def test_jit_provisioning_returns_403_when_disabled(monkeypatch, provider):
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

    callback = await _signed_callback(
        redis_client,
        provider,
        tenant=tenant,
        redirect_uri="https://tenant.nojit.example.com/login/callback",
        frontend_state="",
        correlation_id="corr-no-jit",
        config_version=datetime.now(timezone.utc).isoformat(),
    )

    with pytest.raises(HTTPException) as exc:
        await federation_router.auth_callback(callback, container=container)

    assert exc.value.status_code == 403
    assert "User not found" in exc.value.detail

    # Verify no user was created
    assert user_repo._created_user is None


@pytest.mark.asyncio
async def test_auth_callback_rejects_malformed_state_redirect_uri(
    monkeypatch, provider
):
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

    callback = await _signed_callback(
        redis_client,
        provider,
        tenant=tenant,
        redirect_uri="https://alt.tenant.example.com/auth/callback?x=1",
        frontend_state="",
        correlation_id="corr-malformed-redirect",
        config_version=datetime.now(timezone.utc).isoformat(),
    )

    with pytest.raises(HTTPException) as exc:
        await federation_router.auth_callback(callback, container=container)

    assert exc.value.status_code == 400
    assert "Redirect URI mismatch" in exc.value.detail


@pytest.mark.asyncio
class InterleavingRedis(FakeRedis):
    """Lets the other callback run between a plain read and the later delete,
    as two server workers can; GETDEL reads and deletes in one step."""

    async def get(self, key: str) -> str | None:
        value = self._store.get(key)
        await asyncio.sleep(0)
        return value


class FailingStateRedis(FakeRedis):
    async def get(self, key: str) -> str | None:
        raise ConnectionError("redis unavailable")

    async def getdel(self, key: str) -> str | None:
        raise ConnectionError("redis unavailable")


SINGLE_USE_SLUG = "tenant-single-use"
SINGLE_USE_REDIRECT_URI = "https://tenant.example.com/login/callback"


def _single_use_tenant(
    monkeypatch, redis_client: FakeRedis
) -> tuple[TenantInDB, MockContainer]:
    """A federated tenant with one active member, served from redis_client."""
    dummy_settings = DummySettings(federation_enabled=True)
    monkeypatch.setattr(federation_router, "get_settings", lambda: dummy_settings)
    tenant_id = uuid4()
    tenant = TenantInDB(
        id=tenant_id,
        name="Tenant Single Use",
        display_name="Tenant Single Use",
        slug=SINGLE_USE_SLUG,
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
            "canonical_public_origin": "https://tenant.example.com",
            "redirect_path": "/login/callback",
            "allowed_domains": ["example.com"],
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    user = UserInDB(
        id=uuid4(),
        username="Tester",
        email="user@example.com",
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
    return tenant, container


async def _single_use_callback(
    monkeypatch,
    provider,
    redis_client: FakeRedis,
    *,
    channel: OidcChannel = "api",
    binding_challenge: str | None = None,
):
    """A valid tenant callback whose transaction is stored once in redis_client."""
    tenant, container = _single_use_tenant(monkeypatch, redis_client)
    callback = await _signed_callback(
        FakeRedis() if isinstance(redis_client, FailingStateRedis) else redis_client,
        provider,
        tenant=tenant,
        redirect_uri=SINGLE_USE_REDIRECT_URI,
        frontend_state="{}",
        correlation_id="corr-single-use",
        config_version=datetime.now(timezone.utc).isoformat(),
        channel=channel,
        binding_challenge=binding_challenge,
    )
    return callback, container


async def test_auth_callback_state_is_single_use(monkeypatch, provider):
    callback, container = await _single_use_callback(monkeypatch, provider, FakeRedis())

    first = await federation_router.auth_callback(callback, container=container)
    assert first["access_token"] == "access-token"

    with pytest.raises(OidcTransactionInvalidError):
        await federation_router.auth_callback(callback, container=container)


@pytest.mark.parametrize("bound", [False, True], ids=["unbound", "bound"])
async def test_concurrent_callbacks_admit_exactly_one(monkeypatch, provider, bound):
    verifier = secrets.token_urlsafe(32)
    callback, container = await _single_use_callback(
        monkeypatch,
        provider,
        InterleavingRedis(),
        binding_challenge=code_challenge(verifier) if bound else None,
    )
    if bound:
        callback = callback.model_copy(update={"binding_verifier": verifier})

    results = await asyncio.gather(
        federation_router.auth_callback(callback, container=container),
        federation_router.auth_callback(callback, container=container),
        return_exceptions=True,
    )

    admitted = [r for r in results if isinstance(r, dict)]
    refused = [r for r in results if isinstance(r, BaseException)]
    assert len(admitted) == 1
    assert len(refused) == 1
    assert isinstance(refused[0], OidcTransactionInvalidError)


async def test_state_lookup_failure_is_unavailable(monkeypatch, provider):
    callback, container = await _single_use_callback(
        monkeypatch, provider, FailingStateRedis()
    )

    with pytest.raises(OidcLoginUnavailableError):
        await federation_router.auth_callback(callback, container=container)


def _token_exchanges(provider: FakeOidcProvider) -> int:
    return sum(
        1
        for method, url in provider.requests
        if method == "POST" and url == provider.token_endpoint
    )


def _http(container: MockContainer) -> AsyncClient:
    """The federation routes over HTTP, with the application's error answers."""
    app = FastAPI()
    add_exception_handlers(app)
    app.include_router(federation_router.router)
    for route in endpoint_routes(app.routes):
        for dependency in route.dependant.dependencies if route.dependant else ():
            if dependency.name == "container":
                app.dependency_overrides[dependency.call] = lambda: container
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="https://tenant.example.com"
    )


def _body(callback: CallbackRequest, **extra: str) -> dict[str, str]:
    return {"code": callback.code, "state": callback.state, **extra}


def _stored_transactions(redis_client: FakeRedis) -> list[dict[str, object]]:
    return [json.loads(raw) for raw in redis_client._store.values()]


class TestRedeemerBinding:
    """A client may bind its sign-in by sending the S256 hash of a secret at
    initiate; only the holder of that secret can then redeem the callback.
    Whoever holds a leaked code and state but not the secret is refused, and
    the refusal leaves the owner's sign-in intact."""

    async def test_the_owner_signs_in_with_its_verifier(self, monkeypatch, provider):
        verifier = secrets.token_urlsafe(32)
        callback, container = await _single_use_callback(
            monkeypatch,
            provider,
            FakeRedis(),
            binding_challenge=code_challenge(verifier),
        )

        async with _http(container) as client:
            signed_in = await client.post(
                "/auth/callback", json=_body(callback, binding_verifier=verifier)
            )

        assert signed_in.status_code == 200, signed_in.text
        assert signed_in.json()["access_token"] == "access-token"

    @pytest.mark.parametrize(
        "presented", ["none", "other"], ids=["without-verifier", "other-verifier"]
    )
    async def test_a_leaked_code_and_state_are_refused(
        self, monkeypatch, provider, presented
    ):
        verifier = secrets.token_urlsafe(32)
        callback, container = await _single_use_callback(
            monkeypatch,
            provider,
            FakeRedis(),
            binding_challenge=code_challenge(verifier),
        )
        leaked = (
            _body(callback)
            if presented == "none"
            else _body(callback, binding_verifier=secrets.token_urlsafe(32))
        )

        async with _http(container) as client:
            refused = await client.post("/auth/callback", json=leaked)
            assert refused.status_code == 400
            assert refused.json()["code"] == "oidc_transaction_invalid"
            assert refused.json()["eneo_error_code"] == 9078
            assert _token_exchanges(provider) == 0

            owner = await client.post(
                "/auth/callback", json=_body(callback, binding_verifier=verifier)
            )

        assert owner.status_code == 200, owner.text
        assert _token_exchanges(provider) == 1

    async def test_initiate_stores_the_challenge_and_sends_it_nowhere(
        self, monkeypatch, provider
    ):
        redis_client = FakeRedis()
        _, container = _single_use_tenant(monkeypatch, redis_client)
        challenge = code_challenge(secrets.token_urlsafe(32))

        async with _http(container) as client:
            started = await client.get(
                "/auth/initiate",
                params={"tenant": SINGLE_USE_SLUG, "binding_challenge": challenge},
            )

        assert started.status_code == 200, started.text
        (stored,) = _stored_transactions(redis_client)
        assert (stored["channel"], stored["binding_challenge"]) == ("api", challenge)
        state = jwt.decode(started.json()["state"], options={"verify_signature": False})
        assert challenge not in started.json()["authorization_url"]
        assert challenge not in json.dumps(state)

    @pytest.mark.parametrize(
        "challenge",
        ["A" * 42, "A" * 44, "A" * 42 + "=", "A" * 42 + "+"],
        ids=["short", "long", "padded", "outside-base64url"],
    )
    async def test_a_malformed_challenge_starts_nothing(
        self, monkeypatch, provider, challenge
    ):
        redis_client = FakeRedis()
        _, container = _single_use_tenant(monkeypatch, redis_client)

        async with _http(container) as client:
            refused = await client.get(
                "/auth/initiate",
                params={"tenant": SINGLE_USE_SLUG, "binding_challenge": challenge},
            )

        assert refused.status_code == 422
        assert redis_client._store == {}

    @pytest.mark.parametrize(
        "malformed",
        [
            "A" * 42,
            "A" * 129,
            secrets.token_urlsafe(32) + "+",
        ],
        ids=["short", "long", "outside-unreserved"],
    )
    async def test_a_malformed_verifier_is_refused_and_the_transaction_kept(
        self, monkeypatch, provider, malformed
    ):
        verifier = secrets.token_urlsafe(32)
        callback, container = await _single_use_callback(
            monkeypatch,
            provider,
            FakeRedis(),
            binding_challenge=code_challenge(verifier),
        )

        async with _http(container) as client:
            refused = await client.post(
                "/auth/callback", json=_body(callback, binding_verifier=malformed)
            )
            owner = await client.post(
                "/auth/callback", json=_body(callback, binding_verifier=verifier)
            )

        assert refused.status_code == 422
        assert malformed not in refused.text
        assert owner.status_code == 200, owner.text
        assert _token_exchanges(provider) == 1

    @pytest.mark.parametrize(
        "extra",
        [{}, {"code_verifier": "sent-by-an-older-client"}],
        ids=["code-and-state", "with-ignored-code-verifier"],
    )
    async def test_an_unbound_sign_in_works_as_before(
        self, monkeypatch, provider, extra
    ):
        _, container = _single_use_tenant(monkeypatch, FakeRedis())

        async with _http(container) as client:
            started = await client.get(
                "/auth/initiate", params={"tenant": SINGLE_USE_SLUG}
            )
            answer = provider.authorize(started.json()["authorization_url"])
            signed_in = await client.post(
                "/auth/callback",
                json={
                    "code": answer.code,
                    "state": started.json()["state"],
                    **({"iss": answer.iss} if answer.iss else {}),
                    **extra,
                },
            )

        assert signed_in.status_code == 200, signed_in.text
        assert signed_in.json()["access_token"] == "access-token"

    async def test_a_request_cannot_choose_the_channel(self, monkeypatch, provider):
        redis_client = FakeRedis()
        tenant, container = _single_use_tenant(monkeypatch, redis_client)
        verifier = secrets.token_urlsafe(32)

        async with _http(container) as client:
            started = await client.get(
                "/auth/initiate",
                params={"tenant": SINGLE_USE_SLUG, "channel": "browser"},
            )
            (stored,) = _stored_transactions(redis_client)
            browser = await _signed_callback(
                redis_client,
                provider,
                tenant=tenant,
                redirect_uri=SINGLE_USE_REDIRECT_URI,
                channel="browser",
                binding_challenge=code_challenge(verifier),
            )
            refused = await client.post(
                "/auth/callback",
                json=_body(browser, binding_verifier=verifier, channel="browser"),
            )

        assert started.status_code == 200, started.text
        assert stored["channel"] == "api"
        assert refused.status_code == 400
        assert refused.json()["code"] == "oidc_transaction_invalid"
        assert _token_exchanges(provider) == 0


async def test_initiate_refuses_a_templated_issuer_before_storing_anything(
    monkeypatch, provider
):
    """A config saved before the check, an environment-only config or the
    startup migration can still name a template; initiate stops before any
    transaction or authorization URL exists."""
    redis_client = FakeRedis()
    tenant, container = _single_use_tenant(monkeypatch, redis_client)
    tenant.federation_config["issuer"] = (
        "https://login.microsoftonline.com/{tenantid}/v2.0"
    )

    async with _http(container) as client:
        refused = await client.get("/auth/initiate", params={"tenant": SINGLE_USE_SLUG})

    assert refused.status_code == 500
    assert "template" in refused.json()["detail"]
    assert "authorization_url" not in refused.text
    assert redis_client._store == {}
