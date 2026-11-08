"""Existing OIDC setups keep signing in, out and creating accounts.

Each entry point runs against a fake provider that signs real ID tokens: the
generic login in database federation mode and in environment-only mode, the
browser cookie login, and the provider-bound route the Svelte MobilityGuard
login calls. Signing out of a browser session is pinned in
test_browser_session_router.py; the Svelte logout never calls the backend.
"""

import hashlib
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException, Response

from eneo.authentication import federation_router
from eneo.authentication.auth_service import AuthService
from eneo.authentication.browser_session_service import BrowserSessionService
from eneo.authentication.federation_router import CallbackRequest
from eneo.settings.encryption_service import EncryptionService
from eneo.tenants.tenant import TenantInDB, TenantState
from eneo.users.user import UserInDB
from tests.fake_oidc_provider import DROP, FakeOidcProvider, install
from tests.unittests.authentication.test_federation_router import (
    AuditServiceStub,
    DummySettings,
    FakeRedis,
    MockContainerForJIT,
    TenantRepoStub,
    UserRepoStubForJIT,
)

ORIGIN = "https://eneo.example.org"
REDIRECT_URI = f"{ORIGIN}/login/callback"


def _tenant(provider: FakeOidcProvider, *, db_mode: bool) -> TenantInDB:
    return TenantInDB(
        id=uuid4(),
        name="Example organisation",
        display_name="Example organisation",
        slug="example",
        quota_limit=1024**3,
        state=TenantState.ACTIVE,
        provisioning=True,
        default_role_id=uuid4(),
        modules=[],
        api_credentials={},
        federation_config=provider.federation_config(
            canonical_public_origin=ORIGIN,
            redirect_path="/login/callback",
            allowed_domains=["example.com"],
        )
        if db_mode
        else {},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _settings(provider: FakeOidcProvider, *, db_mode: bool) -> DummySettings:
    if db_mode:
        return DummySettings(federation_enabled=True)
    return DummySettings(
        federation_enabled=False,
        public_origin=ORIGIN,
        oidc_discovery_endpoint=provider.discovery_url,
        oidc_client_id=provider.client_id,
        oidc_client_secret=provider.client_secret,
        oidc_allowed_domains=["example.com"],
    )


class Login:
    """One organisation's login against a fake provider."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        provider: FakeOidcProvider,
        *,
        db_mode: bool = True,
        existing_email: str | None = None,
    ):
        self.provider = provider
        self.settings = _settings(provider, db_mode=db_mode)
        monkeypatch.setattr(federation_router, "get_settings", lambda: self.settings)
        install(monkeypatch, provider)
        self.tenant = _tenant(provider, db_mode=db_mode)
        self.db_mode = db_mode
        existing = None
        if existing_email is not None:
            existing = UserInDB(
                id=uuid4(),
                email=existing_email,
                username=existing_email.split("@")[0],
                tenant=self.tenant,
                tenant_id=self.tenant.id,
                state="active",
            )
        self.users = UserRepoStubForJIT(existing_user=existing, tenant=self.tenant)
        self.audit = AuditServiceStub()
        self.redis = FakeRedis()
        self.container = MockContainerForJIT(
            tenant_repo=TenantRepoStub(self.tenant),
            user_repo=self.users,
            auth_service=AuthService(),
            redis_client=self.redis,
            encryption_service=EncryptionService(None),
            audit_service=self.audit,
        )

    async def initiate(self, frontend_state: str | None = None):
        return await federation_router.initiate_auth(
            response=Response(),
            container=self.container,
            tenant=self.tenant.slug if self.db_mode else None,
            state=frontend_state,
        )

    async def sign_in(self, **claims: Any) -> dict[str, str]:
        started = await self.initiate()
        answer = self.provider.authorize(started.authorization_url, **claims)
        return await federation_router.auth_callback(
            CallbackRequest(code=answer.code, state=started.state), self.container
        )

    def signed_in_user(self, result: dict[str, str]) -> str:
        claims = jwt.decode(
            result["access_token"],
            options={"verify_signature": False},
            algorithms=["HS256"],
        )
        return claims["sub"]


@pytest.mark.parametrize("db_mode", [True, False], ids=["db-mode", "env-mode"])
async def test_existing_member_signs_in(monkeypatch, db_mode):
    login = Login(
        monkeypatch,
        FakeOidcProvider(),
        db_mode=db_mode,
        existing_email="user@example.com",
    )

    result = await login.sign_in()

    assert login.signed_in_user(result)
    assert result["frontend_state"] == ""
    assert login.users._created_user is None
    assert login.redis._store == {}


@pytest.mark.parametrize("db_mode", [True, False], ids=["db-mode", "env-mode"])
async def test_first_sign_in_creates_the_account_once(monkeypatch, db_mode):
    login = Login(monkeypatch, FakeOidcProvider(), db_mode=db_mode)

    await login.sign_in(email="new.person@example.com")

    created = login.users._created_user
    assert created is not None
    assert created.email == "new.person@example.com"
    assert created.tenant_id == login.tenant.id
    assert [
        event["metadata"]["provisioning_method"] for event in login.audit.logged_events
    ] == ["jit_federation"]


async def test_env_mode_creates_the_account_on_the_fallback_verification_claim(
    monkeypatch,
):
    login = Login(monkeypatch, FakeOidcProvider(), db_mode=False)

    await login.sign_in(
        email="fallback@example.com", email_verified=DROP, xms_edov=True
    )

    created = login.users._created_user
    assert created is not None and created.email == "fallback@example.com"


@pytest.mark.parametrize("db_mode", [True, False], ids=["db-mode", "env-mode"])
async def test_explicit_unverified_email_never_falls_back(monkeypatch, db_mode):
    login = Login(monkeypatch, FakeOidcProvider(), db_mode=db_mode)

    with pytest.raises(HTTPException) as refused:
        await login.sign_in(
            email="fallback@example.com", email_verified=False, xms_edov=True
        )

    assert refused.value.status_code == 401
    assert login.users._created_user is None
    assert login.audit.logged_events == []


async def test_a_domain_outside_the_allowlist_is_refused(monkeypatch):
    login = Login(monkeypatch, FakeOidcProvider())

    with pytest.raises(HTTPException) as refused:
        await login.sign_in(email="intruder@outside.example")

    assert refused.value.status_code == 403
    assert login.users._created_user is None


async def test_frontend_state_comes_back_from_the_callback(monkeypatch):
    login = Login(monkeypatch, FakeOidcProvider(), existing_email="user@example.com")

    started = await login.initiate(frontend_state='{"next":"/spaces"}')
    answer = login.provider.authorize(started.authorization_url)
    result = await federation_router.auth_callback(
        CallbackRequest(code=answer.code, state=started.state), login.container
    )

    assert result["frontend_state"] == '{"next":"/spaces"}'


async def test_the_authorization_request_keeps_its_parameters(monkeypatch):
    login = Login(monkeypatch, FakeOidcProvider())

    started = await login.initiate()

    query = parse_qs(urlsplit(started.authorization_url).query)
    assert query["client_id"] == [login.provider.client_id]
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert query["scope"] == ["openid email profile"]
    assert query["state"] == [started.state]


async def test_browser_login_sets_the_session_cookie(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from eneo.main.config import get_settings, set_settings
    from eneo.server.endpoint_routes import endpoint_routes
    from eneo.server.main import get_application

    provider = FakeOidcProvider()
    login = Login(monkeypatch, provider, existing_email="user@example.com")
    login.tenant.federation_config["additional_redirect_uris"] = [
        "https://beta.example.se/login/callback"
    ]
    original = get_settings()
    set_settings(
        original.model_copy(
            update={
                "browser_session_enabled": True,
                "web_app_enabled": False,
                "environment": "production",
                "jwt_secret": login.settings.jwt_secret,
            }
        )
    )
    sessions = AsyncMock(spec=BrowserSessionService)
    sessions.start.side_effect = lambda issued, replacing=None: issued
    login.container.browser_session_service = lambda: sessions
    app = get_application()
    for route in endpoint_routes(app.routes):
        if route.dependant and route.path in (
            "/api/v1/auth/browser/initiate",
            "/login/callback",
        ):
            for dependency in route.dependant.dependencies:
                if dependency.name == "container":
                    app.dependency_overrides[dependency.call] = lambda: login.container
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://beta.example.se",
            follow_redirects=False,
        ) as client:
            started = await client.get(
                "/api/v1/auth/browser/initiate",
                params={"tenant": login.tenant.slug, "next": "/dashboard"},
                headers={"Sec-Fetch-Site": "same-origin"},
            )
            assert started.status_code == 303
            transaction = client.cookies["__Host-eneo_oidc_txn"]
            answer = provider.authorize(started.headers["location"])
            query = parse_qs(urlsplit(started.headers["location"]).query)
            params = {"code": answer.code, "state": query["state"][0]}
            if answer.iss is not None:
                params["iss"] = answer.iss
            finished = await client.get(
                "/login/callback",
                params=params,
                headers={"Sec-Fetch-Site": "cross-site"},
            )
    finally:
        set_settings(original)

    assert finished.status_code == 303
    assert finished.headers["location"] == "/dashboard"
    assert any(
        cookie.startswith("__Host-eneo_web=")
        for cookie in finished.headers.get_list("set-cookie")
    )
    state = jwt.decode(
        query["state"][0], login.settings.jwt_secret, algorithms=["HS256"]
    )
    assert state["frontend_state"].startswith(
        hashlib.sha256(transaction.encode()).hexdigest()
    )


@pytest.mark.parametrize("case", ["member", "jit", "unverified"])
async def test_the_provider_bound_route_keeps_signing_in(monkeypatch, case):
    """The route the Svelte MobilityGuard login posts its code and verifier to."""
    from starlette.requests import Request

    from eneo.authentication.auth_models import OpenIdConnectLogin
    from eneo.users import user_router, user_service

    provider = FakeOidcProvider()
    login = Login(
        monkeypatch,
        provider,
        db_mode=False,
        existing_email="user@example.com" if case == "member" else None,
    )
    login.settings.oidc_tenant_id = str(login.tenant.id)
    monkeypatch.setattr(user_router.config, "get_settings", lambda: login.settings)
    monkeypatch.setattr(user_service, "get_settings", lambda: login.settings)
    claims: dict[str, Any] = {}
    if case == "jit":
        claims = {"email": "new.person@example.com"}
    elif case == "unverified":
        claims = {"email": "new.person@example.com", "email_verified": False}
    code = provider.issue_code(
        client_id=provider.client_id, redirect_uri=REDIRECT_URI, **claims
    )
    body = OpenIdConnectLogin(
        code=code,
        code_verifier="frontend-pkce-verifier",
        client_id=provider.client_id,
        redirect_uri=REDIRECT_URI,
    )
    request = Request({"type": "http", "headers": []})

    with pytest.warns(DeprecationWarning, match="BasicAuth is deprecated"):
        if case == "unverified":
            with pytest.raises(HTTPException) as refused:
                await user_router.login_with_mobilityguard(
                    request, body, login.container
                )
            assert refused.value.status_code == 401
            assert login.users._created_user is None
            return
        token = await user_router.login_with_mobilityguard(
            request, body, login.container
        )

    assert token.access_token
    assert (login.users._created_user is not None) is (case == "jit")
    assert provider.token_requests[0]["code_verifier"] == "frontend-pkce-verifier"
