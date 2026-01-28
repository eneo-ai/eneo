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
    dummy_settings = DummySettings(federation_per_tenant_enabled=True)
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
    dummy_settings = DummySettings(federation_per_tenant_enabled=True)
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


# --- JIT Provisioning Tests ---

from intric.predefined_roles.predefined_role import PredefinedRoleInDB


class PredefinedRolesRepoStub:
    def __init__(self, user_role: PredefinedRoleInDB | None):
        self._user_role = user_role

    async def get_predefined_role_by_name(self, name):
        if self._user_role and self._user_role.name == name.value:
            return self._user_role
        return None


class UserRepoStubForJIT:
    """User repo stub that can simulate a user not existing initially, then being created."""

    def __init__(self, existing_user: UserInDB | None = None, tenant: TenantInDB | None = None):
        self._user = existing_user
        self._tenant = tenant
        self._created_user = None

    async def get_user_by_email(self, email: str):
        if self._user and email.lower() == self._user.email.lower():
            return self._user
        if self._created_user and email.lower() == self._created_user.email.lower():
            return self._created_user
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
        predefined_roles_repo=None,
        audit_service=None,
    ):
        self._tenant_repo = tenant_repo
        self._user_repo = user_repo
        self._auth_service = auth_service
        self._redis_client = redis_client
        self._encryption_service = encryption_service
        self._predefined_roles_repo = predefined_roles_repo
        self._audit_service = audit_service

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

    def predefined_roles_repo(self):
        return self._predefined_roles_repo

    def audit_service(self):
        return self._audit_service


@pytest.mark.asyncio
async def test_jit_provisioning_creates_user_when_enabled(monkeypatch):
    """Test that JIT provisioning creates a user when enabled and user doesn't exist."""
    dummy_settings = DummySettings(federation_per_tenant_enabled=True)
    monkeypatch.setattr(federation_router, "get_settings", lambda: dummy_settings)

    redis_client = FakeRedis()
    tenant_id = uuid4()
    slug = "tenant-jit"
    role_id = uuid4()

    # Tenant with provisioning enabled
    tenant = TenantInDB(
        id=tenant_id,
        name="Tenant JIT",
        display_name="Tenant JIT",
        slug=slug,
        quota_limit=1024**3,
        state=TenantState.ACTIVE,
        provisioning=True,  # JIT provisioning enabled
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

    # User role
    user_role = PredefinedRoleInDB(
        id=role_id,
        name="User",
        permissions=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    # User repo that returns None (user doesn't exist)
    user_repo = UserRepoStubForJIT(existing_user=None, tenant=tenant)
    audit_service = AuditServiceStub()

    container = MockContainerForJIT(
        tenant_repo=TenantRepoStub(tenant),
        user_repo=user_repo,
        auth_service=AuthServiceStub(),
        redis_client=redis_client,
        encryption_service=EncryptionService(None),
        predefined_roles_repo=PredefinedRolesRepoStub(user_role),
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

    signed_state = jwt.encode(state_payload, dummy_settings.jwt_secret, algorithm="HS256")

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

    # Verify login succeeded
    assert result == {"access_token": "access-token"}

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
async def test_jit_provisioning_returns_403_when_disabled(monkeypatch):
    """Test that login fails with 403 when JIT provisioning is disabled and user doesn't exist."""
    dummy_settings = DummySettings(federation_per_tenant_enabled=True)
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
        predefined_roles_repo=None,
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

    signed_state = jwt.encode(state_payload, dummy_settings.jwt_secret, algorithm="HS256")

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
