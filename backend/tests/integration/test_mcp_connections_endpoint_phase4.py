"""Phase 4 invariants: /api/v1/me/mcp-connections status reporting.

The endpoint summarises every accessible MCP server's reachability from
the caller's session. Coverage:

1. ``static_bearer`` server → ``not_applicable`` regardless of cache.
2. ``per_user`` server with cached exchanged token → ``connected`` +
   ``expires_at``.
3. ``per_user`` server with expired cache → ``expired`` (still shows
   ``expires_at`` so the UI can format "expired Xm ago").
4. ``per_user`` server, no IdP token row → ``not_authenticated``.
5. ``per_user`` server, IdP token row exists but for a *different*
   issuer → ``idp_mismatch`` (re-auth at the same IdP won't help).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.mcp_exchanged_tokens_table import MCPExchangedTokens
from intric.database.tables.mcp_server_table import MCPServers


@pytest.fixture
async def default_user(db_container):
    async with db_container() as container:
        user_repo = container.user_repo()
        return await user_repo.get_user_by_email("test@example.com")


@pytest.fixture
async def default_user_token(db_container, patch_auth_service_jwt, default_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(default_user)


async def _insert_server(
    db_container,
    *,
    tenant_id,
    name: str,
    auth_scope: str = "static_bearer",
    expected_idp_issuer: str | None = None,
) -> str:
    async with db_container() as container:
        session = container.session()
        result = await session.execute(
            sa.insert(MCPServers)
            .values(
                tenant_id=tenant_id,
                space_id=None,
                name=name,
                http_url=f"https://mcp-{name}.example/srv",
                http_auth_type="none",
                is_enabled=True,
                auth_scope=auth_scope,
                expected_idp_issuer=expected_idp_issuer,
            )
            .returning(MCPServers.id)
        )
        mcp_id = result.scalar_one()
        await session.commit()
        return str(mcp_id)


async def _insert_exchanged_token_row(
    db_container,
    *,
    mcp_server_id: str,
    tenant_id,
    user_id,
    expires_at: datetime,
    audience: str,
    idp_issuer: str,
) -> None:
    async with db_container() as container:
        session = container.session()
        encryption = container.encryption_service()
        await session.execute(
            sa.insert(MCPExchangedTokens).values(
                mcp_server_id=mcp_server_id,
                tenant_id=tenant_id,
                subject_type="user",
                subject_id=user_id,
                token_ciphertext=encryption.encrypt("cached-token"),
                expires_at=expires_at,
                issued_at=datetime.now(timezone.utc),
                audience=audience,
                idp_issuer=idp_issuer,
            )
        )
        await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_static_bearer_server_reports_not_applicable(
    client, db_container, default_user, default_user_token
):
    sid = await _insert_server(
        db_container,
        tenant_id=default_user.tenant_id,
        name=f"static-{uuid4().hex[:6]}",
        auth_scope="static_bearer",
    )
    response = await client.get(
        "/api/v1/me/mcp-connections",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 200, response.text
    items = {item["mcp_server_id"]: item for item in response.json()["items"]}
    assert items[sid]["status"] == "not_applicable"
    assert items[sid]["expires_at"] is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_per_user_server_with_active_cache_reports_connected(
    client, db_container, default_user, default_user_token
):
    issuer = "https://keycloak.example/realms/eneo"
    sid = await _insert_server(
        db_container,
        tenant_id=default_user.tenant_id,
        name=f"peruser-{uuid4().hex[:6]}",
        auth_scope="per_user",
        expected_idp_issuer=issuer,
    )
    future = datetime.now(timezone.utc) + timedelta(minutes=30)
    await _insert_exchanged_token_row(
        db_container,
        mcp_server_id=sid,
        tenant_id=default_user.tenant_id,
        user_id=default_user.id,
        expires_at=future,
        audience=f"https://mcp-peruser-{uuid4().hex[:6]}.example/srv",
        idp_issuer=issuer,
    )

    response = await client.get(
        "/api/v1/me/mcp-connections",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 200, response.text
    items = {item["mcp_server_id"]: item for item in response.json()["items"]}
    assert items[sid]["status"] == "connected"
    assert items[sid]["expires_at"] is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_per_user_server_with_expired_cache_reports_expired(
    client, db_container, default_user, default_user_token
):
    issuer = "https://keycloak.example/realms/eneo"
    sid = await _insert_server(
        db_container,
        tenant_id=default_user.tenant_id,
        name=f"expired-{uuid4().hex[:6]}",
        auth_scope="per_user",
        expected_idp_issuer=issuer,
    )
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    await _insert_exchanged_token_row(
        db_container,
        mcp_server_id=sid,
        tenant_id=default_user.tenant_id,
        user_id=default_user.id,
        expires_at=past,
        audience="https://mcp.example/expired",
        idp_issuer=issuer,
    )

    response = await client.get(
        "/api/v1/me/mcp-connections",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 200, response.text
    items = {item["mcp_server_id"]: item for item in response.json()["items"]}
    assert items[sid]["status"] == "expired"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_per_user_server_with_no_idp_token_reports_not_authenticated(
    client, db_container, default_user, default_user_token
):
    issuer = "https://keycloak.example/realms/eneo"
    sid = await _insert_server(
        db_container,
        tenant_id=default_user.tenant_id,
        name=f"noauth-{uuid4().hex[:6]}",
        auth_scope="per_user",
        expected_idp_issuer=issuer,
    )

    response = await client.get(
        "/api/v1/me/mcp-connections",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 200, response.text
    items = {item["mcp_server_id"]: item for item in response.json()["items"]}
    assert items[sid]["status"] == "not_authenticated"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_per_user_server_with_wrong_issuer_reports_idp_mismatch(
    client, db_container, default_user, default_user_token
):
    server_issuer = "https://keycloak.example/realms/eneo"
    user_issuer = "https://entra.example/v2.0"

    sid = await _insert_server(
        db_container,
        tenant_id=default_user.tenant_id,
        name=f"mismatch-{uuid4().hex[:6]}",
        auth_scope="per_user",
        expected_idp_issuer=server_issuer,
    )

    # Seed the user with an IdP token row for a *different* issuer
    async with db_container() as container:
        await container.oidc_token_store().upsert(
            user=default_user,
            idp_issuer=user_issuer,
            idp_subject="user-1",
            refresh_token="rt",
            access_token="at",
            access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes_granted=["openid"],
        )

    response = await client.get(
        "/api/v1/me/mcp-connections",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 200, response.text
    items = {item["mcp_server_id"]: item for item in response.json()["items"]}
    assert items[sid]["status"] == "idp_mismatch"
