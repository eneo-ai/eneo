"""Tests for OIDC resource-server mode: IdP access tokens as bearer auth.

Tokens are validated against the issuer's JWKS (discovery-resolved, cached
in-process) and resolved to users with the same allowed-domain / JIT
provisioning rules as the federation callback. All token problems must
surface as 401-mapping exceptions, never 500s.
"""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from eneo.authentication import oidc_resource_server
from eneo.authentication.auth_service import AuthService
from eneo.main.exceptions import AuthenticationException, UniqueException
from eneo.tenants.tenant import TenantInDB, TenantState
from eneo.users import user_service as user_service_module
from eneo.users.user import UserInDB
from eneo.users.user_service import UserService

ISSUER = "https://idp.example.com"
AUDIENCE = "eneo-backend"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
JWKS_URL = f"{ISSUER}/jwks"


def _generate_key(kid: str):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return private_pem, jwk


def _make_idp_token(
    private_pem: bytes,
    kid: str,
    *,
    iss: str = ISSUER,
    aud: str = AUDIENCE,
    email: str | None = "user@example.com",
    exp_offset: int = 3600,
    algorithm: str = "RS256",
) -> str:
    now = int(time.time())
    payload = {
        "iss": iss,
        "aud": aud,
        "sub": "idp-subject-id",
        "iat": now - 5,
        "exp": now + exp_offset,
    }
    if email is not None:
        payload["email"] = email
    return jwt.encode(payload, private_pem, algorithm=algorithm, headers={"kid": kid})


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


class FakeHttpClient:
    """Maps URL -> payload (or callable returning payload); records GETs."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url: str, *args, **kwargs):  # noqa: ARG002
        self.calls.append(url)
        payload = self.routes[url]
        if callable(payload):
            payload = payload()
        return FakeResponse(payload)


def _make_tenant(*, provisioning: bool = False, **overrides) -> TenantInDB:
    defaults = dict(
        id=uuid4(),
        name="Test Tenant",
        display_name="Test Tenant",
        slug="test-tenant",
        quota_limit=1024**3,
        state=TenantState.ACTIVE,
        provisioning=provisioning,
        modules=[],
        api_credentials={},
    )
    defaults.update(overrides)
    return TenantInDB(**defaults)


def _make_user(email: str, tenant: TenantInDB) -> UserInDB:
    return UserInDB(
        id=uuid4(),
        username=email.split("@")[0],
        email=email,
        salt=None,
        password=None,
        used_tokens=0,
        tenant_id=tenant.id,
        tenant=tenant,
        quota_limit=1024**3,
        user_groups=[],
        roles=[],
        state="active",
    )


class UserRepoStub:
    def __init__(self, tenant: TenantInDB, users: list[UserInDB] | None = None):
        self.tenant = tenant
        self.users_by_email = {u.email.lower(): u for u in users or []}
        self.add_calls = 0

    async def get_user_by_email(self, email: str):
        return self.users_by_email.get(email.lower())

    async def get_user_by_username(self, username: str):
        for user in self.users_by_email.values():
            if user.username == username:
                return user
        return None

    async def add(self, user_add):
        self.add_calls += 1
        key = user_add.email.lower()
        if key in self.users_by_email:
            raise UniqueException("User already exists.")
        user = _make_user(user_add.email, self.tenant)
        self.users_by_email[key] = user
        return user


class RacingUserRepoStub(UserRepoStub):
    """Holds the first two email lookups until both arrived, so two
    concurrent first requests both observe "user does not exist yet"."""

    def __init__(self, tenant: TenantInDB):
        super().__init__(tenant)
        self._lookups = 0
        self._both_looked_up = asyncio.Event()

    async def get_user_by_email(self, email: str):
        self._lookups += 1
        if self._lookups == 2:
            self._both_looked_up.set()
        if self._lookups <= 2:
            await self._both_looked_up.wait()
            return None
        return await super().get_user_by_email(email)


class TenantRepoStub:
    def __init__(self, tenant: TenantInDB):
        self._tenant = tenant

    async def get(self, tenant_id):
        if self._tenant.id == tenant_id:
            return self._tenant
        return None

    async def get_all_active(self):
        return [self._tenant]


class AuditServiceStub:
    def __init__(self):
        self.logged_events = []

    async def log(self, **kwargs):
        self.logged_events.append(kwargs)


def _make_settings(**overrides) -> SimpleNamespace:
    defaults = dict(
        jwt_secret="unit-test-secret-padded-to-the-hs256-minimum",
        oidc_resource_server_enabled=True,
        oidc_accepted_issuer=ISSUER,
        oidc_accepted_audience=AUDIENCE,
        oidc_jwks_cache_ttl_seconds=3600,
        oidc_tenant_id=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_user_service(user_repo, tenant_repo, audit_service) -> UserService:
    return UserService(
        user_repo=user_repo,
        auth_service=AuthService(AsyncMock()),
        api_key_auth_resolver=MagicMock(),
        api_key_v2_repo=MagicMock(),
        audit_service=audit_service,
        settings_repo=MagicMock(),
        tenant_repo=tenant_repo,
        info_blob_repo=MagicMock(),
    )


@pytest.fixture(autouse=True)
def fresh_jwks_cache():
    oidc_resource_server.reset_jwks_cache()
    yield
    oidc_resource_server.reset_jwks_cache()


@pytest.fixture
def idp_key():
    return _generate_key("kid-a")


@pytest.fixture
def setup(monkeypatch, idp_key):
    """Default harness: one active tenant, one existing user, one JWKS key."""
    private_pem, jwk = idp_key
    tenant = _make_tenant()
    user = _make_user("user@example.com", tenant)
    user_repo = UserRepoStub(tenant, users=[user])
    tenant_repo = TenantRepoStub(tenant)
    audit_service = AuditServiceStub()

    http = FakeHttpClient(
        {
            DISCOVERY_URL: {"jwks_uri": JWKS_URL},
            JWKS_URL: {"keys": [jwk]},
        }
    )

    settings = _make_settings()
    monkeypatch.setattr(user_service_module, "get_settings", lambda: settings)
    monkeypatch.setattr(oidc_resource_server, "get_settings", lambda: settings)
    monkeypatch.setattr(oidc_resource_server, "aiohttp_client", lambda: http)

    service = _make_user_service(user_repo, tenant_repo, audit_service)

    return SimpleNamespace(
        private_pem=private_pem,
        tenant=tenant,
        user=user,
        user_repo=user_repo,
        tenant_repo=tenant_repo,
        audit_service=audit_service,
        http=http,
        settings=settings,
        service=service,
    )


@pytest.mark.asyncio
async def test_valid_idp_token_resolves_correct_user(setup):
    token = _make_idp_token(setup.private_pem, "kid-a")

    user = await setup.service.authenticate(token=token)

    assert user.id == setup.user.id
    assert user.email == "user@example.com"


@pytest.mark.asyncio
async def test_eneo_hs256_jwt_still_works_with_resource_server_enabled(setup):
    token = setup.service.auth_service.create_access_token_for_user(
        user=setup.user, secret_key=setup.settings.jwt_secret
    )

    user = await setup.service.authenticate(token=token)

    assert user.id == setup.user.id
    # The Eneo-JWT path never touches discovery or JWKS.
    assert setup.http.calls == []


@pytest.mark.asyncio
async def test_wrong_audience_is_rejected(setup):
    token = _make_idp_token(setup.private_pem, "kid-a", aud="another-api")

    with pytest.raises(AuthenticationException):
        await setup.service.authenticate(token=token)


@pytest.mark.asyncio
async def test_wrong_issuer_is_rejected(setup):
    token = _make_idp_token(setup.private_pem, "kid-a", iss="https://evil.example.com")

    with pytest.raises(AuthenticationException):
        await setup.service.authenticate(token=token)


@pytest.mark.asyncio
async def test_opaque_token_yields_authentication_error_not_500(setup):
    with pytest.raises(AuthenticationException):
        await setup.service.authenticate(token="opaque-reference-token-12345")


@pytest.mark.asyncio
async def test_token_without_email_claim_is_rejected(setup):
    token = _make_idp_token(setup.private_pem, "kid-a", email=None)

    with pytest.raises(AuthenticationException):
        await setup.service.authenticate(token=token)


@pytest.mark.asyncio
async def test_unknown_email_with_provisioning_off_is_forbidden(setup):
    token = _make_idp_token(setup.private_pem, "kid-a", email="new@example.com")

    with pytest.raises(HTTPException) as exc:
        await setup.service.authenticate(token=token)

    assert exc.value.status_code == 403
    assert setup.user_repo.add_calls == 0


@pytest.mark.asyncio
async def test_provisioning_on_creates_user_with_audit_row(monkeypatch, idp_key):
    private_pem, jwk = idp_key
    tenant = _make_tenant(provisioning=True)
    user_repo = UserRepoStub(tenant)
    audit_service = AuditServiceStub()
    http = FakeHttpClient(
        {DISCOVERY_URL: {"jwks_uri": JWKS_URL}, JWKS_URL: {"keys": [jwk]}}
    )

    settings = _make_settings()
    monkeypatch.setattr(user_service_module, "get_settings", lambda: settings)
    monkeypatch.setattr(oidc_resource_server, "get_settings", lambda: settings)
    monkeypatch.setattr(oidc_resource_server, "aiohttp_client", lambda: http)

    service = _make_user_service(user_repo, TenantRepoStub(tenant), audit_service)
    token = _make_idp_token(private_pem, "kid-a", email="new@example.com")

    user = await service.authenticate(token=token)

    assert user.email == "new@example.com"
    assert user.tenant_id == tenant.id
    assert user_repo.add_calls == 1
    assert len(audit_service.logged_events) == 1
    event = audit_service.logged_events[0]
    assert event["metadata"]["provisioning_method"] == "jit_federation"
    assert event["tenant_id"] == tenant.id


@pytest.mark.asyncio
async def test_concurrent_first_requests_create_one_user_one_audit_row(
    monkeypatch, idp_key
):
    private_pem, jwk = idp_key
    tenant = _make_tenant(provisioning=True)
    user_repo = RacingUserRepoStub(tenant)
    audit_service = AuditServiceStub()
    http = FakeHttpClient(
        {DISCOVERY_URL: {"jwks_uri": JWKS_URL}, JWKS_URL: {"keys": [jwk]}}
    )

    settings = _make_settings()
    monkeypatch.setattr(user_service_module, "get_settings", lambda: settings)
    monkeypatch.setattr(oidc_resource_server, "get_settings", lambda: settings)
    monkeypatch.setattr(oidc_resource_server, "aiohttp_client", lambda: http)

    service = _make_user_service(user_repo, TenantRepoStub(tenant), audit_service)
    token = _make_idp_token(private_pem, "kid-a", email="new@example.com")

    user_one, user_two = await asyncio.gather(
        service.authenticate(token=token),
        service.authenticate(token=token),
    )

    # Both requests resolve to the same single user...
    assert user_one.id == user_two.id
    assert len(user_repo.users_by_email) == 1
    # ...both raced into the insert, and exactly one audit row was emitted.
    assert user_repo.add_calls == 2
    assert len(audit_service.logged_events) == 1


@pytest.mark.asyncio
async def test_jwks_key_rotation_refetches_once_and_succeeds(setup):
    # Prime the cache with the original key set (kid-a only).
    await setup.service.authenticate(token=_make_idp_token(setup.private_pem, "kid-a"))
    assert setup.http.calls.count(JWKS_URL) == 1

    # IdP rotates: a new signing key appears in the published JWKS.
    rotated_pem, rotated_jwk = _generate_key("kid-b")
    original_jwk = setup.http.routes[JWKS_URL]["keys"][0]
    setup.http.routes[JWKS_URL] = {"keys": [original_jwk, rotated_jwk]}

    user = await setup.service.authenticate(token=_make_idp_token(rotated_pem, "kid-b"))

    assert user.id == setup.user.id
    # Unknown kid triggered exactly one refetch.
    assert setup.http.calls.count(JWKS_URL) == 2


@pytest.mark.asyncio
async def test_unknown_kid_after_refetch_is_rejected(setup):
    # Prime the cache so the unknown kid hits the rotation-refetch path.
    await setup.service.authenticate(token=_make_idp_token(setup.private_pem, "kid-a"))

    unknown_pem, _ = _generate_key("kid-unknown")
    token = _make_idp_token(unknown_pem, "kid-unknown")

    with pytest.raises(AuthenticationException):
        await setup.service.authenticate(token=token)

    # One priming fetch plus exactly one rotation refetch, then failure.
    assert setup.http.calls.count(JWKS_URL) == 2
