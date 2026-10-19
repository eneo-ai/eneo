"""Which token an OAuth server gets at request time, per strategy, and what
happens when none is available or the server refuses it."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet

from eneo.main.exceptions import MCPUserActionRequiredError
from eneo.mcp_servers.application.mcp_oauth_token_provider import (
    MCPOAuthTokenProvider,
)
from eneo.mcp_servers.domain.entities.mcp_oauth_connection import (
    STRATEGY_AUTH_CODE,
    STRATEGY_CLIENT_CREDENTIALS,
    STRATEGY_ID_JAG,
    IdpUserToken,
    MCPOAuthClientRegistration,
    MCPOAuthConnection,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    AUTH_SCOPE_SHARED,
    OAUTH_AUTH_TYPE,
    MCPServer,
)
from eneo.mcp_servers.domain.repositories.mcp_oauth_repo import MCPOAuthRepository
from eneo.mcp_servers.infrastructure.oauth.bearer_auth import MCPOAuthBearerAuth
from eneo.mcp_servers.infrastructure.oauth.discovery import OAuthChallenge
from eneo.settings.encryption_service import EncryptionService
from tests.unit.mcp_servers.infrastructure.oauth.fake_authorization_server import (
    FakeAuthorizationServer,
    unsigned_jwt,
)

SETTINGS = SimpleNamespace(public_origin="https://eneo.example", api_prefix="/api/v1")


class FakeOAuthRepo(MCPOAuthRepository):
    def __init__(self) -> None:
        self.connections: dict[tuple[UUID, Optional[UUID]], MCPOAuthConnection] = {}
        self.registrations: dict[tuple[UUID, str], MCPOAuthClientRegistration] = {}
        self.idp_tokens: dict[UUID, IdpUserToken] = {}
        self.saves = 0

    async def get_connection(self, *, mcp_server_id, user_id):
        return self.connections.get((mcp_server_id, user_id))

    async def list_connections(self, *, mcp_server_ids, user_id):
        return [
            c
            for (sid, uid), c in self.connections.items()
            if sid in mcp_server_ids and uid == user_id
        ]

    async def save_connection(self, connection):
        self.saves += 1
        connection.id = connection.id or uuid4()
        connection.created_at = connection.created_at or datetime.now(timezone.utc)
        self.connections[(connection.mcp_server_id, connection.user_id)] = connection
        return connection

    async def delete_connection(self, *, mcp_server_id, user_id):
        return self.connections.pop((mcp_server_id, user_id), None) is not None

    async def delete_server_state(self, *, mcp_server_id):
        for key in [k for k in self.connections if k[0] == mcp_server_id]:
            del self.connections[key]
        for key in [k for k in self.registrations if k[0] == mcp_server_id]:
            del self.registrations[key]

    async def get_registration(self, *, mcp_server_id, issuer):
        return self.registrations.get((mcp_server_id, issuer))

    async def save_registration(self, registration):
        registration.id = registration.id or uuid4()
        self.registrations[(registration.mcp_server_id, registration.issuer)] = (
            registration
        )
        return registration

    async def get_idp_token(self, *, user_id):
        return self.idp_tokens.get(user_id)

    async def save_idp_token(self, token):
        self.idp_tokens[token.user_id] = token
        return token


def _encryption() -> EncryptionService:
    return EncryptionService(
        SimpleNamespace(encryption_key=Fernet.generate_key().decode())  # type: ignore[arg-type]
    )


def _user(*, federation: Optional[dict] = None, service_key: bool = False):
    tenant = SimpleNamespace(federation_config=federation or {})
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        tenant=tenant,
        permissions=[],
        active_api_key=SimpleNamespace(ownership="service") if service_key else None,
    )


def _server(
    vendor: FakeAuthorizationServer, user, *, shared: bool = False, config=None
):
    return MCPServer(
        id=uuid4(),
        tenant_id=user.tenant_id,
        name="Vendor",
        http_url=vendor.server_url,
        http_auth_type=OAUTH_AUTH_TYPE,
        auth_scope=AUTH_SCOPE_SHARED if shared else "per_user",
        http_auth_config_schema=config,
    )


def _provider(repo, user, redis=None) -> MCPOAuthTokenProvider:
    return MCPOAuthTokenProvider(
        repo=repo,
        encryption_service=_encryption(),
        settings=SETTINGS,  # type: ignore[arg-type]
        user=user,  # type: ignore[arg-type]
        redis_client=redis,
    )


def _connection(
    server, user_id, *, expires_in: int, refresh: Optional[str] = "refresh-0"
):
    return MCPOAuthConnection(
        tenant_id=server.tenant_id,
        mcp_server_id=server.id,
        user_id=user_id,
        issuer="https://vendor.example",
        resource="https://vendor.example/mcp",
        strategy=STRATEGY_AUTH_CODE,
        access_token="access-0",
        refresh_token=refresh,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        id=uuid4(),
    )


# -- per user ----------------------------------------------------------------


async def test_a_fresh_token_is_used_as_is(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)
    user = _user()
    repo = FakeOAuthRepo()
    server = _server(vendor, user)
    connection = _connection(server, user.id, expires_in=3600)
    repo.connections[(server.id, user.id)] = connection

    provider = _provider(repo, user)
    await provider.preload([server])
    auth = await provider.auth_for(server)

    assert isinstance(auth, MCPOAuthBearerAuth)
    assert await provider.access_token_for(server) == "access-0"
    assert vendor.token_requests == []


async def test_a_stale_token_is_refreshed_once_and_the_rotation_kept(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.live_refresh_tokens.add("refresh-0")
    vendor.install(monkeypatch)
    user = _user()
    repo = FakeOAuthRepo()
    server = _server(vendor, user)
    repo.connections[(server.id, user.id)] = _connection(server, user.id, expires_in=10)

    provider = _provider(repo, user)
    token = await provider.access_token_for(server)

    assert token == "access-1"
    saved = repo.connections[(server.id, user.id)]
    assert saved.refresh_token == "refresh-1"
    assert saved.is_connected
    # CIMD is the client identity when nothing is pre-registered.
    assert (
        vendor.token_requests[-1]["client_id"]
        == "https://eneo.example/api/v1/mcp-oauth/client.json"
    )


async def test_a_dead_refresh_token_needs_a_new_authorization(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.fail_refresh_with = "invalid_grant"
    vendor.install(monkeypatch)
    user = _user()
    repo = FakeOAuthRepo()
    server = _server(vendor, user)
    repo.connections[(server.id, user.id)] = _connection(server, user.id, expires_in=0)

    with pytest.raises(MCPUserActionRequiredError) as info:
        await _provider(repo, user).access_token_for(server)

    assert info.value.reason == "invalid_grant"
    assert (
        info.value.connect_url
        == f"https://eneo.example/mcp-oauth/connect?server={server.id}"
    )
    stored = repo.connections[(server.id, user.id)]
    assert stored.status == "needs_authorization"
    assert stored.access_token is None and stored.refresh_token is None


async def test_no_connection_means_the_user_must_connect(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)
    user = _user()
    server = _server(vendor, user)

    with pytest.raises(MCPUserActionRequiredError) as info:
        await _provider(FakeOAuthRepo(), user).access_token_for(server)

    remedy = info.value.remedy()
    assert remedy["code"] == "mcp_authorization_required"
    assert remedy["auth_scope"] == "per_user"
    assert remedy["reason"] == "not_connected"
    assert remedy["connect_url"].endswith(f"?server={server.id}")


async def test_a_service_key_has_no_per_user_connection(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)
    user = _user(service_key=True)
    server = _server(vendor, user)

    with pytest.raises(MCPUserActionRequiredError) as info:
        await _provider(FakeOAuthRepo(), user).access_token_for(server)

    assert info.value.reason == "no_user_identity"
    assert info.value.connect_url is None


async def test_record_denial_invalidates_and_carries_the_challenge_scopes(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)
    user = _user()
    repo = FakeOAuthRepo()
    server = _server(vendor, user)
    repo.connections[(server.id, user.id)] = _connection(
        server, user.id, expires_in=3600
    )
    provider = _provider(repo, user)
    auth = await provider.auth_for(server)
    auth.challenge = OAuthChallenge(
        status_code=403,
        resource_metadata_url=None,
        scope="mcp:write",
        error="insufficient_scope",
    )

    error = await provider.record_denial(server, auth)

    assert error is not None
    assert error.reason == "insufficient_scope"
    assert error.scopes == ["mcp:write"]
    assert repo.connections[(server.id, user.id)].status == "needs_authorization"


async def test_record_denial_without_a_challenge_keeps_the_token(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)
    user = _user()
    repo = FakeOAuthRepo()
    server = _server(vendor, user)
    repo.connections[(server.id, user.id)] = _connection(
        server, user.id, expires_in=3600
    )
    provider = _provider(repo, user)
    auth = await provider.auth_for(server)

    assert await provider.record_denial(server, auth) is None
    assert repo.connections[(server.id, user.id)].is_connected


class CopyingOAuthRepo(FakeOAuthRepo):
    """Hands out copies like a real repository does: two providers never
    share one connection object."""

    async def get_connection(self, *, mcp_server_id, user_id):
        import copy

        row = self.connections.get((mcp_server_id, user_id))
        return copy.deepcopy(row) if row is not None else None

    async def list_connections(self, *, mcp_server_ids, user_id):
        import copy

        return [
            copy.deepcopy(c)
            for c in await super().list_connections(
                mcp_server_ids=mcp_server_ids, user_id=user_id
            )
        ]


async def test_two_providers_with_the_same_stale_token_refresh_once(monkeypatch):
    """The second refresher re-reads the row under the lock and takes the
    first one's result instead of spending the rotated-away refresh token
    and tearing the connection down."""
    vendor = FakeAuthorizationServer()
    vendor.live_refresh_tokens.add("refresh-0")
    vendor.install(monkeypatch)
    user = _user()
    repo = CopyingOAuthRepo()
    server = _server(vendor, user)
    repo.connections[(server.id, user.id)] = _connection(server, user.id, expires_in=10)
    first, second = _provider(repo, user), _provider(repo, user)
    await first.preload([server])
    await second.preload([server])  # both hold a copy of the stale row

    assert await first.access_token_for(server) == "access-1"
    assert await second.access_token_for(server) == "access-1"

    refreshes = [
        r for r in vendor.token_requests if r.get("grant_type") == "refresh_token"
    ]
    assert len(refreshes) == 1
    stored = repo.connections[(server.id, user.id)]
    assert stored.is_connected and stored.refresh_token == "refresh-1"


async def test_tokens_bound_to_another_address_are_never_sent(monkeypatch):
    """An administrator pointed the row at a new address: the tokens issued
    for the old resource read as no connection at all."""
    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)
    user = _user()
    repo = FakeOAuthRepo()
    server = _server(vendor, user)
    repo.connections[(server.id, user.id)] = _connection(
        server, user.id, expires_in=3600
    )
    server.http_url = "https://other-vendor.example/mcp"

    with pytest.raises(MCPUserActionRequiredError) as info:
        await _provider(repo, user).access_token_for(server)

    assert info.value.reason == "not_connected"
    assert vendor.token_requests == []


# -- ID-JAG ------------------------------------------------------------------


def _federation_with_id_jag(vendor: FakeAuthorizationServer) -> dict:
    return {
        "id_jag_enabled": True,
        "client_id": "eneo-federation",
        "client_secret": "s3cret",
        "token_endpoint": vendor.idp_token_endpoint,
    }


async def test_id_jag_is_used_when_both_ends_support_it(monkeypatch):
    vendor = FakeAuthorizationServer(id_jag=True)
    vendor.install(monkeypatch)
    user = _user(federation=_federation_with_id_jag(vendor))
    repo = FakeOAuthRepo()
    repo.idp_tokens[user.id] = IdpUserToken(
        user_id=user.id,
        tenant_id=user.tenant_id,
        idp_issuer="https://idp.example",
        idp_subject="u",
        id_token=unsigned_jwt({"sub": "u"}),
    )
    server = _server(vendor, user)

    token = await _provider(repo, user).access_token_for(server)

    assert token == "access-1"
    saved = repo.connections[(server.id, user.id)]
    assert saved.strategy == STRATEGY_ID_JAG
    grants = [r.get("grant_type") for r in vendor.token_requests]
    assert grants == [
        "urn:ietf:params:oauth:grant-type:token-exchange",
        "urn:ietf:params:oauth:grant-type:jwt-bearer",
    ]


async def test_id_jag_denied_by_the_idp_falls_back_to_the_popup(monkeypatch):
    vendor = FakeAuthorizationServer(id_jag=True)
    vendor.fail_id_jag_with = "access_denied"
    vendor.install(monkeypatch)
    user = _user(federation=_federation_with_id_jag(vendor))
    repo = FakeOAuthRepo()
    repo.idp_tokens[user.id] = IdpUserToken(
        user_id=user.id,
        tenant_id=user.tenant_id,
        idp_issuer="https://idp.example",
        idp_subject="u",
        id_token=unsigned_jwt({"sub": "u"}),
    )
    server = _server(vendor, user)

    with pytest.raises(MCPUserActionRequiredError) as info:
        await _provider(repo, user).access_token_for(server)
    assert info.value.reason == "not_connected"


async def test_id_jag_is_skipped_when_the_server_does_not_advertise_it(monkeypatch):
    vendor = FakeAuthorizationServer(id_jag=False)
    vendor.install(monkeypatch)
    user = _user(federation=_federation_with_id_jag(vendor))
    repo = FakeOAuthRepo()
    repo.idp_tokens[user.id] = IdpUserToken(
        user_id=user.id,
        tenant_id=user.tenant_id,
        idp_issuer="https://idp.example",
        idp_subject="u",
        id_token=unsigned_jwt({"sub": "u"}),
    )
    server = _server(vendor, user)

    with pytest.raises(MCPUserActionRequiredError):
        await _provider(repo, user).access_token_for(server)
    assert vendor.token_requests == []


# -- shared ------------------------------------------------------------------


async def test_shared_client_credentials_mint_and_cache_a_machine_token(monkeypatch):
    vendor = FakeAuthorizationServer(
        client_credentials=True, auth_methods=("client_secret_basic",)
    )
    vendor.install(monkeypatch)
    user = _user()
    repo = FakeOAuthRepo()
    server = _server(
        vendor,
        user,
        shared=True,
        config={"client_id": "pre", "client_secret": "s3cret"},
    )
    provider = _provider(repo, user)

    first = await provider.access_token_for(server)
    second = await provider.access_token_for(server)

    assert first == second == "access-1"
    saved = repo.connections[(server.id, None)]
    assert saved.strategy == STRATEGY_CLIENT_CREDENTIALS and saved.is_shared
    assert (
        len(
            [
                r
                for r in vendor.token_requests
                if r.get("grant_type") == "client_credentials"
            ]
        )
        == 1
    )


async def test_shared_without_a_connection_asks_for_an_admin(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)
    user = _user()
    server = _server(vendor, user, shared=True)

    with pytest.raises(MCPUserActionRequiredError) as info:
        await _provider(FakeOAuthRepo(), user).access_token_for(server)

    assert info.value.auth_scope == "shared"
    assert info.value.connect_url is None


async def test_shared_service_account_connection_serves_every_user(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)
    admin = _user()
    other = SimpleNamespace(**{**vars(admin), "id": uuid4()})
    repo = FakeOAuthRepo()
    server = _server(vendor, admin, shared=True)
    repo.connections[(server.id, None)] = _connection(server, None, expires_in=3600)

    assert await _provider(repo, other, None).access_token_for(server) == "access-0"


async def test_a_repo_factory_opens_a_repository_per_database_access(monkeypatch):
    """In production every access gets its own short session, so the provider
    keeps working while a turn streams after the request's transaction ended."""
    from contextlib import asynccontextmanager

    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)
    user = _user()
    repo = FakeOAuthRepo()
    server = _server(vendor, user)
    repo.connections[(server.id, user.id)] = _connection(
        server, user.id, expires_in=3600
    )
    opened = 0

    @asynccontextmanager
    async def factory():
        nonlocal opened
        opened += 1
        yield repo

    provider = MCPOAuthTokenProvider(
        repo_factory=factory,
        encryption_service=_encryption(),
        settings=SETTINGS,  # type: ignore[arg-type]
        user=user,  # type: ignore[arg-type]
    )
    await provider.preload([server])
    assert await provider.access_token_for(server) == "access-0"
    assert opened == 1

    with pytest.raises(ValueError, match="repo or a repo_factory"):
        MCPOAuthTokenProvider(
            encryption_service=_encryption(),
            settings=SETTINGS,  # type: ignore[arg-type]
            user=user,  # type: ignore[arg-type]
        )
