"""Invariants for the MCP server OAuth schema surface.

Phase 1 lands ``auth_scope`` + ``expected_idp_issuer`` on ``mcp_servers``
and the admin-API gate that rejects ``per_user`` / ``per_tenant`` until
the token-exchange broker is enabled. The invariants verified here:

1. Pre-existing rows have a non-null ``auth_scope`` and it
   defaults to ``static_bearer`` — nothing in the runtime path was paying
   attention to a NULL value before, so accidentally introducing one
   would skew the future broker's branching.
2. The admin POST endpoint returns 501 with a stable error code when an
   operator opts into ``per_user`` or ``per_tenant`` while the broker is
   still off (``MCP_OAUTH_ENABLED=false``).
3. Public DTO surfaces the new ``auth_scope`` / ``expected_idp_issuer``
   fields so the SvelteKit dialog can render them without follow-up
   migrations.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.mcp_server_table import MCPServers


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


async def _insert_mcp_row(
    db_container,
    *,
    tenant_id,
    name: str,
    auth_scope: str | None = None,
    expected_idp_issuer: str | None = None,
) -> str:
    """Insert directly to bypass the live connection probe.

    When ``auth_scope`` is ``None`` the DB default kicks in — that is what
    a row created before the migration looks like after upgrade.
    """
    async with db_container() as container:
        session = container.session()
        values: dict[str, object] = {
            "tenant_id": tenant_id,
            "name": name,
            "http_url": "https://example.invalid/mcp",
            "http_auth_type": "none",
            "is_enabled": True,
        }
        if auth_scope is not None:
            values["auth_scope"] = auth_scope
        if expected_idp_issuer is not None:
            values["expected_idp_issuer"] = expected_idp_issuer
        result = await session.execute(
            sa.insert(MCPServers).values(**values).returning(MCPServers.id)
        )
        mcp_id = result.scalar_one()
        await session.commit()
        return str(mcp_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_existing_rows_default_to_static_bearer(
    client, db_container, default_user, default_user_token
):
    """A row inserted without ``auth_scope`` reads back as ``static_bearer``."""
    mcp_id = await _insert_mcp_row(
        db_container,
        tenant_id=default_user.tenant_id,
        name=f"legacy-{uuid4().hex[:8]}",
    )

    response = await client.get(
        "/api/v1/mcp-servers/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 200, response.text
    row = next(item for item in response.json()["items"] if item["id"] == mcp_id)
    assert row["auth_scope"] == "static_bearer"
    assert row["expected_idp_issuer"] is None


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["per_user", "per_tenant"])
async def test_create_rejects_oauth_scopes_when_flag_disabled(
    client, default_user_token, scope
):
    """POST /mcp-servers/ with per_user / per_tenant returns 501 by default."""
    response = await client.post(
        "/api/v1/mcp-servers/",
        json={
            "name": f"oauth-{uuid4().hex[:8]}",
            "http_url": "https://example.invalid/mcp",
            "http_auth_type": "none",
            "auth_scope": scope,
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 501, response.text
    body = response.json()
    detail = body.get("detail")
    assert isinstance(detail, dict)
    assert detail.get("code") == "mcp_oauth_not_enabled"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_static_bearer_round_trip_includes_expected_idp_issuer(
    client, db_container, default_user, default_user_token
):
    """``expected_idp_issuer`` round-trips through the public DTO."""
    issuer = "https://keycloak.example/realms/eneo"
    mcp_id = await _insert_mcp_row(
        db_container,
        tenant_id=default_user.tenant_id,
        name=f"with-issuer-{uuid4().hex[:8]}",
        auth_scope="static_bearer",
        expected_idp_issuer=issuer,
    )

    response = await client.get(
        "/api/v1/mcp-servers/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 200, response.text
    row = next(item for item in response.json()["items"] if item["id"] == mcp_id)
    assert row["auth_scope"] == "static_bearer"
    assert row["expected_idp_issuer"] == issuer
