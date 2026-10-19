"""The connect flow: registration priority, PKCE and resource on the
authorization request, single-use state, RFC 9207 issuer checks, and where
the tokens land for per-user and shared servers."""

import json
from types import SimpleNamespace
from typing import Optional
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet

from eneo.main.exceptions import BadRequestException, UnauthorizedException
from eneo.mcp_servers.application.mcp_oauth_service import MCPOAuthService
from eneo.mcp_servers.application.mcp_oauth_token_provider import (
    MCPOAuthTokenProvider,
)
from eneo.mcp_servers.domain.entities.mcp_oauth_connection import (
    MCPOAuthClientRegistration,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    AUTH_SCOPE_SHARED,
    OAUTH_AUTH_TYPE,
    MCPServer,
)
from eneo.mcp_servers.infrastructure.oauth.client_assertion import jwks_document
from eneo.roles.permissions import Permission
from eneo.settings.encryption_service import EncryptionService
from tests.unit.mcp_servers.application.test_mcp_oauth_token_provider import (
    FakeOAuthRepo,
)
from tests.unit.mcp_servers.infrastructure.oauth.fake_authorization_server import (
    FakeAuthorizationServer,
)

SETTINGS = SimpleNamespace(public_origin="https://eneo.example", api_prefix="/api/v1")
CIMD = "https://eneo.example/api/v1/mcp-oauth/client.json"
CONFIDENTIAL_CIMD = "https://eneo.example/api/v1/mcp-oauth/client-confidential.json"
JWKS = "https://eneo.example/api/v1/mcp-oauth/jwks.json"


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def getdel(self, key):
        return self.store.pop(key, None)

    async def delete(self, key):
        self.store.pop(key, None)


class FakeServerRepo:
    def __init__(self, servers: list[MCPServer]) -> None:
        self.servers = {s.id: s for s in servers}

    async def one_or_none(self, id: UUID):
        return self.servers.get(id)

    async def query(self, tags=None, **filters):
        return [
            s for s in self.servers.values() if s.tenant_id == filters.get("tenant_id")
        ]


def _encryption() -> EncryptionService:
    return EncryptionService(
        SimpleNamespace(encryption_key=Fernet.generate_key().decode())  # type: ignore[arg-type]
    )


def _user(*, admin: bool = False):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        tenant=SimpleNamespace(federation_config={}),
        permissions=[Permission.ADMIN] if admin else [],
        active_api_key=None,
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


def _service(
    user,
    servers,
    repo: Optional[FakeOAuthRepo] = None,
    redis: Optional[FakeRedis] = None,
):
    repo = repo or FakeOAuthRepo()
    redis = redis or FakeRedis()
    encryption = _encryption()
    provider = MCPOAuthTokenProvider(
        repo=repo,
        encryption_service=encryption,
        settings=SETTINGS,
        user=user,  # type: ignore[arg-type]
    )
    service = MCPOAuthService(
        user=user,  # type: ignore[arg-type]
        mcp_server_repo=FakeServerRepo(servers),  # type: ignore[arg-type]
        repo=repo,
        encryption_service=encryption,
        settings=SETTINGS,  # type: ignore[arg-type]
        redis_client=redis,  # type: ignore[arg-type]
        token_provider=provider,
    )
    return service, repo, redis


def _params(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


async def test_authorize_url_uses_cimd_pkce_and_resource(monkeypatch):
    vendor = FakeAuthorizationServer(challenge_scope="mcp:read")
    vendor.install(monkeypatch)
    user = _user()
    server = _server(vendor, user)
    service, _, redis = _service(user, [server])

    result = await service.authorize_url(server.id)

    params = _params(result["url"])
    assert params["client_id"] == CIMD
    assert params["redirect_uri"] == "https://eneo.example/mcp-oauth/callback"
    assert params["resource"] == vendor.resource
    assert params["scope"] == "mcp:read"
    assert params["code_challenge_method"] == "S256"
    assert params["state"] == result["state"]
    pending = json.loads(redis.store[f"mcp_oauth:state:{result['state']}"])
    assert pending["issuer"] == vendor.issuer
    assert pending["user_id"] == str(user.id)
    # Nothing was registered: the CIMD URL is portable.
    assert vendor.registrations == []


async def test_admin_scope_override_beats_the_servers_scopes(monkeypatch):
    vendor = FakeAuthorizationServer(challenge_scope="mcp:read mcp:write mcp:admin")
    vendor.install(monkeypatch)
    user = _user()
    server = _server(vendor, user, config={"scope": "mcp:read"})
    service, _, _ = _service(user, [server])

    result = await service.authorize_url(server.id)

    assert _params(result["url"])["scope"] == "mcp:read"


async def test_dcr_is_the_fallback_and_is_remembered_per_issuer(monkeypatch):
    vendor = FakeAuthorizationServer(cimd=False)
    vendor.install(monkeypatch)
    user = _user()
    server = _server(vendor, user)
    service, repo, _ = _service(user, [server])

    first = await service.authorize_url(server.id)
    second = await service.authorize_url(server.id)

    assert _params(first["url"])["client_id"] == "dcr-client-1"
    assert _params(second["url"])["client_id"] == "dcr-client-1"
    assert len(vendor.registrations) == 1
    assert vendor.registrations[0]["application_type"] == "web"
    saved = repo.registrations[(server.id, vendor.issuer)]
    assert saved.source == "dcr"


async def test_a_server_that_accepts_private_key_jwt_gets_the_confidential_identity(
    monkeypatch,
):
    vendor = FakeAuthorizationServer(auth_methods=("private_key_jwt", "none"))
    vendor.install(monkeypatch)
    user = _user()
    server = _server(vendor, user)
    service, repo, _ = _service(user, [server])
    vendor.client_jwks = lambda: jwks_document(repo.signing_keys)

    started = await service.authorize_url(server.id)
    code, state = vendor.authorize(started["url"])
    public = await service.complete(server.id, code=code, state=state)

    assert _params(started["url"])["client_id"] == CONFIDENTIAL_CIMD
    assert public["status"] == "connected"
    assert vendor.assertions[-1]["iss"] == CONFIDENTIAL_CIMD
    assert vendor.assertions[-1]["aud"] == f"{vendor.base}/oauth2/token"
    # One deployment key, made on first use.
    assert len(repo.signing_keys) == 1
    assert vendor.registrations == []


async def test_dcr_registers_the_confidential_client_when_the_server_allows(
    monkeypatch,
):
    vendor = FakeAuthorizationServer(cimd=False, auth_methods=("private_key_jwt",))
    vendor.install(monkeypatch)
    user = _user()
    server = _server(vendor, user)
    service, repo, _ = _service(user, [server])
    vendor.client_jwks = lambda: jwks_document(repo.signing_keys)

    started = await service.authorize_url(server.id)
    code, state = vendor.authorize(started["url"])
    await service.complete(server.id, code=code, state=state)

    request = vendor.registrations[0]
    assert request["token_endpoint_auth_method"] == "private_key_jwt"
    assert request["jwks_uri"] == JWKS
    assert request["token_endpoint_auth_signing_alg"] == "ES256"
    saved = repo.registrations[(server.id, vendor.issuer)]
    assert saved.client_secret is None
    assert saved.registration_payload["token_endpoint_auth_method"] == "private_key_jwt"
    assert vendor.assertions[-1]["iss"] == "dcr-client-1"


async def test_a_pre_registered_client_can_opt_into_private_key_jwt(monkeypatch):
    vendor = FakeAuthorizationServer(auth_methods=("private_key_jwt",))
    vendor.install(monkeypatch)
    user = _user()
    server = _server(
        vendor,
        user,
        config={"client_id": "pre", "client_auth_method": "private_key_jwt"},
    )
    service, repo, _ = _service(user, [server])
    vendor.client_jwks = lambda: jwks_document(repo.signing_keys)

    started = await service.authorize_url(server.id)
    code, state = vendor.authorize(started["url"])
    public = await service.complete(server.id, code=code, state=state)

    assert public["status"] == "connected"
    assert vendor.assertions[-1]["iss"] == "pre"


async def test_pre_registered_client_wins(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)
    user = _user()
    server = _server(
        vendor, user, config={"client_id": "pre", "client_secret": "s3cret"}
    )
    service, _, _ = _service(user, [server])

    result = await service.authorize_url(server.id)

    assert _params(result["url"])["client_id"] == "pre"


async def test_no_registration_path_is_an_admin_problem(monkeypatch):
    vendor = FakeAuthorizationServer(cimd=False, dcr=False)
    vendor.install(monkeypatch)
    user = _user()
    server = _server(vendor, user)
    service, _, _ = _service(user, [server])

    with pytest.raises(BadRequestException, match="pre-registered client id"):
        await service.authorize_url(server.id)


async def test_complete_stores_the_users_connection(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)
    user = _user()
    server = _server(vendor, user)
    service, repo, _ = _service(user, [server])
    started = await service.authorize_url(server.id)
    code, state = vendor.authorize(started["url"])

    public = await service.complete(server.id, code=code, state=state)

    assert public["status"] == "connected"
    assert public["auth_scope"] == "per_user"
    saved = repo.connections[(server.id, user.id)]
    assert saved.access_token == "access-1"
    assert saved.refresh_token == "refresh-1"
    assert saved.connected_by_user_id == user.id
    assert vendor.token_requests[-1]["resource"] == vendor.resource
    assert (
        vendor.token_requests[-1]["redirect_uri"]
        == "https://eneo.example/mcp-oauth/callback"
    )


async def test_state_is_single_use(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)
    user = _user()
    server = _server(vendor, user)
    service, _, _ = _service(user, [server])
    started = await service.authorize_url(server.id)
    code, state = vendor.authorize(started["url"])
    await service.complete(server.id, code=code, state=state)

    with pytest.raises(BadRequestException, match="Unknown or expired"):
        await service.complete(server.id, code=code, state=state)


async def test_another_users_state_is_rejected(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)
    alice, bob = _user(), _user()
    server = _server(vendor, alice)
    repo, redis = FakeOAuthRepo(), FakeRedis()
    alice_service, _, _ = _service(alice, [server], repo, redis)
    bob_service, _, _ = _service(bob, [server], repo, redis)
    started = await alice_service.authorize_url(server.id)
    code, state = vendor.authorize(started["url"])

    with pytest.raises(BadRequestException, match="another user"):
        await bob_service.complete(server.id, code=code, state=state)


async def test_iss_is_compared_when_present_and_required_when_advertised(monkeypatch):
    vendor = FakeAuthorizationServer(iss_param=True)
    vendor.install(monkeypatch)
    user = _user()
    server = _server(vendor, user)
    service, _, _ = _service(user, [server])

    started = await service.authorize_url(server.id)
    code, state = vendor.authorize(started["url"])
    with pytest.raises(BadRequestException, match="unexpected issuer"):
        await service.complete(
            server.id, code=code, state=state, iss="https://evil.example"
        )

    started = await service.authorize_url(server.id)
    code, state = vendor.authorize(started["url"])
    with pytest.raises(BadRequestException, match="missing the iss"):
        await service.complete(server.id, code=code, state=state)

    started = await service.authorize_url(server.id)
    code, state = vendor.authorize(started["url"])
    assert (
        await service.complete(server.id, code=code, state=state, iss=vendor.issuer)
    )["status"] == "connected"


async def test_an_issuer_published_with_a_trailing_slash_round_trips(monkeypatch):
    vendor = FakeAuthorizationServer(iss_param=True, issuer="https://vendor.example/")
    vendor.install(monkeypatch)
    user = _user()
    server = _server(vendor, user)
    service, _, _ = _service(user, [server])
    started = await service.authorize_url(server.id)
    code, state = vendor.authorize(started["url"])

    public = await service.complete(
        server.id, code=code, state=state, iss="https://vendor.example/"
    )

    assert public["status"] == "connected"


async def test_a_present_iss_is_checked_even_when_not_advertised(monkeypatch):
    vendor = FakeAuthorizationServer(iss_param=False)
    vendor.install(monkeypatch)
    user = _user()
    server = _server(vendor, user)
    service, _, _ = _service(user, [server])
    started = await service.authorize_url(server.id)
    code, state = vendor.authorize(started["url"])

    with pytest.raises(BadRequestException, match="unexpected issuer"):
        await service.complete(
            server.id, code=code, state=state, iss="https://evil.example"
        )


async def test_shared_servers_are_connected_by_admins_only(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)
    admin = _user(admin=True)
    member = _user()
    member.tenant_id = admin.tenant_id
    server = _server(vendor, admin, shared=True)
    repo, redis = FakeOAuthRepo(), FakeRedis()
    member_service, _, _ = _service(member, [server], repo, redis)
    admin_service, _, _ = _service(admin, [server], repo, redis)

    with pytest.raises(UnauthorizedException):
        await member_service.authorize_url(server.id)

    started = await admin_service.authorize_url(server.id)
    code, state = vendor.authorize(started["url"])
    public = await admin_service.complete(server.id, code=code, state=state)

    assert public["auth_scope"] == "shared"
    assert (server.id, None) in repo.connections
    assert public["connected_by_user_id"] == str(admin.id)
    # Every member sees the shared connection as connected.
    states = await member_service.connections_for([server])
    assert states[0]["status"] == "connected"


async def test_disconnect_revokes_and_forgets(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)
    user = _user()
    server = _server(vendor, user)
    service, repo, _ = _service(user, [server])
    started = await service.authorize_url(server.id)
    code, state = vendor.authorize(started["url"])
    await service.complete(server.id, code=code, state=state)

    assert await service.disconnect(server.id) is True

    assert (server.id, user.id) not in repo.connections
    assert vendor.revoked == ["refresh-1"]
    assert await service.disconnect(server.id) is False


async def test_connection_states_cover_every_oauth_server(monkeypatch):
    vendor = FakeAuthorizationServer()
    vendor.install(monkeypatch)
    user = _user()
    connected = _server(vendor, user)
    untouched = _server(vendor, user)
    plain = MCPServer(
        id=uuid4(), tenant_id=user.tenant_id, name="Plain", http_url="https://x/mcp"
    )
    service, _, _ = _service(user, [connected, untouched, plain])
    started = await service.authorize_url(connected.id)
    code, state = vendor.authorize(started["url"])
    await service.complete(connected.id, code=code, state=state)

    states = {s["mcp_server_id"]: s["status"] for s in await service.my_connections()}

    assert states == {
        str(connected.id): "connected",
        str(untouched.id): "not_connected",
    }


async def test_registration_stores_no_secret_in_the_payload(monkeypatch):
    vendor = FakeAuthorizationServer(cimd=False, auth_methods=("client_secret_basic",))
    vendor.install(monkeypatch)
    user = _user()
    server = _server(vendor, user)
    service, repo, _ = _service(user, [server])

    await service.authorize_url(server.id)

    saved: MCPOAuthClientRegistration = repo.registrations[(server.id, vendor.issuer)]
    assert saved.client_secret == "s3cret"
    assert "client_secret" not in (saved.registration_payload or {})
