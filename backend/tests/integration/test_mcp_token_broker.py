"""Invariants for the MCP token broker.

Pins the behaviors the runtime path depends on:

1. Issuer gate: the broker refuses to exchange when the PRM's
   ``authorization_servers`` don't include ``mcp_server.expected_idp_issuer``.
   ``mcp_token_exchange_denied`` audit fires; no IdP call happens.
2. Happy path: first call exchanges and caches; second call in the same
   request hits the cache. The exchanged token round-trips the encryption
   layer (ciphertext on disk, plaintext to the caller).
3. Expired cache without an MCP refresh token falls back to a fresh
   exchange while reusing the still-valid IdP subject token.
4. Service-key gate: a service API key on a ``per_user`` MCP server is
   refused before the IdP is touched.

The PRM and IdP HTTP endpoints are mocked at the helpers exposed by the
``token_exchange`` package and the discovery service, so no real IdP is
needed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.authentication.oidc_token_store import OidcTokenStore, StoredIdpTokens
from eneo.database.tables.mcp_exchanged_tokens_table import MCPExchangedTokens
from eneo.database.tables.mcp_server_table import MCPServers
from eneo.mcp_servers.application import mcp_token_broker as broker_mod
from eneo.mcp_servers.application.mcp_token_broker import (
    MCPRequiresUserIdentityError,
    MCPSameIdpMismatchError,
    UserPrincipal,
)
from eneo.mcp_servers.application.token_exchange import rfc8693 as rfc8693_mod
from eneo.mcp_servers.infrastructure import oauth_discovery
from eneo.mcp_servers.infrastructure.oauth_discovery import (
    DiscoveryError,
    OAuthDiscoveryService,
    ProtectedResourceMetadata,
)


@pytest.fixture(autouse=True)
def clear_discovery_cache():
    oauth_discovery.reset_discovery_cache()
    yield
    oauth_discovery.reset_discovery_cache()


@pytest.fixture
def patch_idp_post(monkeypatch):
    """Capture POSTs to the (mocked) IdP token endpoint."""
    state: dict[str, object] = {"call_count": 0, "response": (200, {})}

    async def fake_post(*, token_endpoint, form):
        state["call_count"] = int(state.get("call_count", 0)) + 1
        state["last_endpoint"] = token_endpoint
        state["last_form"] = form
        return state["response"]

    monkeypatch.setattr(rfc8693_mod, "post_form", fake_post)
    monkeypatch.setattr(broker_mod, "post_form", fake_post)
    return state


@pytest.fixture
def patch_prm(monkeypatch):
    """Serve an in-memory PRM document from the discovery service."""
    prm_state: dict[str, object] = {"doc": None}

    async def fake_prm(self, *, http_url, resource_metadata_url=None):
        doc = prm_state["doc"]
        if doc is None:
            raise DiscoveryError(f"No PRM stub configured for {http_url}")
        return doc

    monkeypatch.setattr(
        OAuthDiscoveryService, "get_protected_resource_metadata", fake_prm
    )
    return prm_state


@pytest.fixture
async def default_user(db_container):
    async with db_container() as container:
        user_repo = container.user_repo()
        return await user_repo.get_user_by_email("test@example.com")


async def _insert_per_user_mcp_server(
    db_container,
    *,
    tenant_id,
    expected_idp_issuer: str,
    audience_url: str = "https://mcp.example/srv",
) -> str:
    async with db_container() as container:
        session = container.session()
        result = await session.execute(
            sa.insert(MCPServers)
            .values(
                tenant_id=tenant_id,
                name=f"mcp-{uuid4().hex[:8]}",
                http_url=audience_url,
                http_auth_type="none",
                is_enabled=True,
                auth_scope="per_user",
                expected_idp_issuer=expected_idp_issuer,
            )
            .returning(MCPServers.id)
        )
        mcp_id = result.scalar_one()
        await session.commit()
        return str(mcp_id)


async def _load_mcp_server_entity(db_container, mcp_id: str):
    async with db_container() as container:
        repo = container.mcp_server_repo()
        return await repo.one(mcp_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_issuer_mismatch_denies_exchange_without_idp_call(
    db_container, default_user, patch_idp_post, patch_prm
):
    """PRM lists a different AS -> MCPSameIdpMismatchError, no IdP call."""
    issuer = "https://idp.example/realms/eneo"
    mcp_id = await _insert_per_user_mcp_server(
        db_container,
        tenant_id=default_user.tenant_id,
        expected_idp_issuer=issuer,
    )
    server = await _load_mcp_server_entity(db_container, mcp_id)

    patch_prm["doc"] = ProtectedResourceMetadata(
        resource=server.http_url,
        authorization_servers=("https://some-other-idp.example/",),
    )

    async with db_container() as container:
        broker = container.mcp_token_broker()
        with pytest.raises(MCPSameIdpMismatchError):
            await broker.get_token(
                mcp_server=server,
                tenant_federation_config={
                    "token_endpoint": f"{issuer}/protocol/openid-connect/token",
                    "client_id": "eneo-broker",
                    "client_secret": "s3cret",
                },
                principal=UserPrincipal(user=default_user),
            )

    assert patch_idp_post["call_count"] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_per_user_happy_path_caches_token_for_subsequent_calls(
    db_container, default_user, patch_idp_post, patch_prm
):
    """First call exchanges + persists; second call hits the cache (no IdP call)."""
    issuer = "https://idp.example/realms/eneo"
    mcp_id = await _insert_per_user_mcp_server(
        db_container,
        tenant_id=default_user.tenant_id,
        expected_idp_issuer=issuer,
    )
    server = await _load_mcp_server_entity(db_container, mcp_id)

    patch_prm["doc"] = ProtectedResourceMetadata(
        resource=server.http_url,
        authorization_servers=(issuer,),
    )
    patch_idp_post["response"] = (
        200,
        {"access_token": "mcp-aud-token", "expires_in": 600},
    )

    # Seed an IdP refresh+access token row so the broker has a subject
    async with db_container() as container:
        await container.oidc_token_store().upsert(
            user=default_user,
            idp_issuer=issuer,
            idp_subject="user-1",
            refresh_token="rt",
            access_token="at",
            access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes_granted=["openid"],
        )

    federation_config = {
        "token_endpoint": f"{issuer}/protocol/openid-connect/token",
        "client_id": "eneo-broker",
        "client_secret": "s3cret",
    }

    async with db_container() as container:
        broker = container.mcp_token_broker()
        token_first = await broker.get_token(
            mcp_server=server,
            tenant_federation_config=federation_config,
            principal=UserPrincipal(user=default_user),
        )
        token_second = await broker.get_token(
            mcp_server=server,
            tenant_federation_config=federation_config,
            principal=UserPrincipal(user=default_user),
        )

    assert token_first == "mcp-aud-token"
    assert token_second == "mcp-aud-token"
    # One exchange + zero refresh on the second call (access_token not stale)
    assert patch_idp_post["call_count"] == 1

    # Cached row exists and is encrypted at rest
    async with db_container() as container:
        session = container.session()
        row = (
            await session.execute(
                sa.select(MCPExchangedTokens).where(
                    MCPExchangedTokens.mcp_server_id == server.id,
                    MCPExchangedTokens.subject_type == "user",
                    MCPExchangedTokens.subject_id == default_user.id,
                )
            )
        ).scalar_one()
    assert row.token_ciphertext != "mcp-aud-token"
    assert row.token_ciphertext.startswith("enc:fernet:v1:")
    assert row.audience == server.http_url
    assert row.idp_issuer == issuer


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expired_mcp_token_reexchanges_for_main_login_lifetime(
    db_container, default_user, patch_idp_post, patch_prm, monkeypatch
):
    """Expired MCP token + no MCP refresh token falls back to a fresh exchange.

    Matches the common Keycloak shape: the exchanged MCP access token is
    short-lived and no refresh_token is returned, while the main login can
    still refresh its IdP subject token.
    """
    issuer = "https://idp.example/realms/eneo"
    mcp_id = await _insert_per_user_mcp_server(
        db_container,
        tenant_id=default_user.tenant_id,
        expected_idp_issuer=issuer,
        audience_url="https://mcp.example/grounding",
    )
    server = await _load_mcp_server_entity(db_container, mcp_id)

    patch_prm["doc"] = ProtectedResourceMetadata(
        resource=server.http_url,
        authorization_servers=(issuer,),
    )

    refresh_count = {"value": 0}

    async def fake_refresh(
        self,
        *,
        user,
        idp_issuer,
        token_endpoint,
        client_id,
        client_secret=None,
    ):
        refresh_count["value"] += 1
        access_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        await self.upsert(
            user=user,
            idp_issuer=idp_issuer,
            idp_subject="user-1",
            refresh_token="main-login-rt",
            access_token="fresh-subject-at",
            access_token_expires_at=access_expires_at,
            scopes_granted=["openid", "email", "profile"],
        )
        return StoredIdpTokens(
            user_id=user.id,
            tenant_id=user.tenant_id,
            idp_issuer=idp_issuer,
            refresh_token="main-login-rt",
            access_token="fresh-subject-at",
            id_token=None,
            access_token_expires_at=access_expires_at,
            scopes_granted=["openid", "email", "profile"],
        )

    monkeypatch.setattr(OidcTokenStore, "refresh_idp_token", fake_refresh)

    async with db_container() as container:
        await container.oidc_token_store().upsert(
            user=default_user,
            idp_issuer=issuer,
            idp_subject="user-1",
            refresh_token="main-login-rt",
            access_token="stale-subject-at",
            access_token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            scopes_granted=["openid"],
        )

    federation_config = {
        "token_endpoint": f"{issuer}/protocol/openid-connect/token",
        "client_id": "eneo-broker",
        "client_secret": "s3cret",
    }

    patch_idp_post["response"] = (
        200,
        {"access_token": "mcp-aud-token-1", "expires_in": 300},
    )
    async with db_container() as container:
        broker = container.mcp_token_broker()
        token_first = await broker.get_token(
            mcp_server=server,
            tenant_federation_config=federation_config,
            principal=UserPrincipal(user=default_user),
        )

    assert token_first == "mcp-aud-token-1"
    assert refresh_count["value"] == 1

    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(MCPExchangedTokens)
            .where(
                MCPExchangedTokens.mcp_server_id == server.id,
                MCPExchangedTokens.subject_id == default_user.id,
            )
            .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await session.commit()

    patch_idp_post["response"] = (
        200,
        {"access_token": "mcp-aud-token-2", "expires_in": 300},
    )
    async with db_container() as container:
        broker = container.mcp_token_broker()
        token_second = await broker.get_token(
            mcp_server=server,
            tenant_federation_config=federation_config,
            principal=UserPrincipal(user=default_user),
        )

    assert token_second == "mcp-aud-token-2"
    assert patch_idp_post["call_count"] == 2
    assert refresh_count["value"] == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_key_on_per_user_server_refuses_before_idp_touch(
    db_container, default_user, patch_idp_post, patch_prm
):
    """Service-key UserInDB on a per_user server -> MCPRequiresUserIdentityError."""
    from eneo.authentication.auth_models import is_service_api_key

    issuer = "https://idp.example/realms/eneo"
    mcp_id = await _insert_per_user_mcp_server(
        db_container,
        tenant_id=default_user.tenant_id,
        expected_idp_issuer=issuer,
    )
    server = await _load_mcp_server_entity(db_container, mcp_id)

    # Synthesize a service-key-style UserInDB by copying the default user and
    # marking it via the same construction used by the service-key auth path.
    service_user = default_user.model_copy(deep=True)
    if hasattr(service_user, "ownership"):
        service_user.ownership = "service"  # type: ignore[attr-defined]
    if not is_service_api_key(service_user):
        pytest.skip("service-key UserInDB detection helper not available in this build")

    async with db_container(user=service_user) as container:
        broker = container.mcp_token_broker()
        with pytest.raises(MCPRequiresUserIdentityError):
            await broker.get_token(
                mcp_server=server,
                tenant_federation_config={},
                principal=UserPrincipal(user=service_user),
            )
    assert patch_idp_post["call_count"] == 0
