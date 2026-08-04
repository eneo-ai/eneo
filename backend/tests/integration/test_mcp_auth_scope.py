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

from eneo.database.tables.mcp_server_table import MCPServers, MCPServerTools


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
    client, default_user_token, scope, monkeypatch
):
    """POST /mcp-servers/ with per_user / per_tenant returns 501 while the
    broker flag is off. Pinned explicitly: the surrounding environment may
    run with MCP_OAUTH_ENABLED=true."""
    from eneo.main.config import get_settings

    monkeypatch.setattr(get_settings(), "mcp_oauth_enabled", False)
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
    # The HTTPException handler flattens {code, message} details to the
    # top-level body.
    assert response.json().get("code") == "mcp_oauth_not_enabled"


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


@pytest.mark.parametrize("scope", ["per_user", "per_tenant"])
async def test_create_sso_scope_saves_without_connection_probe(
    client, default_user_token, scope, monkeypatch
):
    """POST /mcp-servers/ with an SSO scope persists the server without
    probing the remote: the broker mints tokens per user at call time, so
    there are no admin-time credentials to probe with. The unreachable URL
    proves no probe ran (a probe would 400 the request). Tools arrive later
    via tools/sync, so the catalog starts empty."""
    from eneo.main.config import get_settings

    monkeypatch.setattr(get_settings(), "mcp_oauth_enabled", True)
    headers = {"Authorization": f"Bearer {default_user_token}"}

    response = await client.post(
        "/api/v1/mcp-servers/",
        json={
            "name": f"sso-{scope}-{uuid4().hex[:8]}",
            "http_url": "https://example.invalid/mcp",
            "http_auth_type": "bearer",
            "auth_scope": scope,
            "exchange_protocol": "id_jag",
            "expected_idp_issuer": "https://idp.example/oauth2/default",
            "target_resource_or_scope": "https://example.invalid/mcp",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["connection"]["success"] is True
    assert body["connection"]["probe_skipped"] is True
    assert body["connection"]["tools_discovered"] == 0
    assert body["server"]["auth_scope"] == scope

    server_id = body["server"]["id"]
    tools = await client.get(f"/api/v1/mcp-servers/{server_id}/tools/", headers=headers)
    assert tools.status_code == 200, tools.text
    assert tools.json()["items"] == []


async def test_create_sso_scope_with_declared_tool_catalog(
    client, default_user_token, monkeypatch
):
    """A headless provisioner registers a per_user server together with its
    tool catalog: SSO servers cannot be probed without a user session, so
    the declared ``tools`` become the initial catalog, saved as approved on
    the registering admin's authority. The runtime proxy still intersects
    this catalog with the live per-user tools/list before exposure."""
    from eneo.main.config import get_settings

    monkeypatch.setattr(get_settings(), "mcp_oauth_enabled", True)
    headers = {"Authorization": f"Bearer {default_user_token}"}

    response = await client.post(
        "/api/v1/mcp-servers/",
        json={
            "name": f"sso-tools-{uuid4().hex[:8]}",
            "http_url": "https://example.invalid/mcp",
            "http_auth_type": "bearer",
            "auth_scope": "per_user",
            "exchange_protocol": "id_jag",
            "expected_idp_issuer": "https://idp.example/oauth2/default",
            "target_resource_or_scope": "https://example.invalid/mcp",
            "tools": [
                {
                    "name": "search_knowledge",
                    "title": "Search knowledge",
                    "description": "Search the connected knowledge base.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
                {"name": "get_document"},
            ],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["connection"]["probe_skipped"] is True
    assert body["connection"]["tools_discovered"] == 2

    server_id = body["server"]["id"]
    tools = await client.get(f"/api/v1/mcp-servers/{server_id}/tools/", headers=headers)
    assert tools.status_code == 200, tools.text
    by_name = {item["name"]: item for item in tools.json()["items"]}
    assert set(by_name) == {"search_knowledge", "get_document"}
    search = by_name["search_knowledge"]
    assert search["description"] == "Search the connected knowledge base."
    assert search["input_schema"]["required"] == ["query"]
    # Declared tools are active immediately: approved (nothing pending) and
    # enabled, so the runtime can expose them without a human review step.
    assert search["requires_approval"] is False
    assert search["pending_description"] is None
    assert search["is_enabled_by_default"] is True


async def test_update_replaces_declared_tool_catalog(
    client, db_container, default_user_token, monkeypatch
):
    """Re-declaring the catalog on update makes the stored set match exactly:
    kept tools take the new definition (name-stable, so assistant selections
    survive), absent tools are deleted, new tools appear, and staged
    unapproved drift on a re-declared tool resolves to the declaration."""
    from eneo.main.config import get_settings

    monkeypatch.setattr(get_settings(), "mcp_oauth_enabled", True)
    headers = {"Authorization": f"Bearer {default_user_token}"}

    created = await client.post(
        "/api/v1/mcp-servers/",
        json={
            "name": f"sso-redeclare-{uuid4().hex[:8]}",
            "http_url": "https://example.invalid/mcp",
            "http_auth_type": "bearer",
            "auth_scope": "per_user",
            "expected_idp_issuer": "https://idp.example/oauth2/default",
            "tools": [
                {"name": "search_knowledge", "description": "Old description."},
                {"name": "get_document"},
            ],
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    server_id = created.json()["server"]["id"]

    # Simulate drift staged by an earlier sync: pending values awaiting review
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(MCPServerTools)
            .where(
                MCPServerTools.mcp_server_id == server_id,
                MCPServerTools.name == "search_knowledge",
            )
            .values(pending_description="Drifted remote text", requires_approval=True)
        )
        await session.commit()

    updated = await client.post(
        f"/api/v1/mcp-servers/{server_id}/",
        json={
            "tools": [
                {"name": "search_knowledge", "description": "New description."},
                {"name": "list_sources"},
            ]
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text

    tools = await client.get(f"/api/v1/mcp-servers/{server_id}/tools/", headers=headers)
    by_name = {item["name"]: item for item in tools.json()["items"]}
    assert set(by_name) == {"search_knowledge", "list_sources"}
    search = by_name["search_knowledge"]
    assert search["description"] == "New description."
    assert search["requires_approval"] is False
    assert search["pending_description"] is None


async def test_create_rejects_invalid_declared_tool_catalog(
    client, default_user_token, monkeypatch
):
    """The declared catalog passes the same validation as live discovery;
    duplicate tool names are rejected before anything is persisted."""
    from eneo.main.config import get_settings

    monkeypatch.setattr(get_settings(), "mcp_oauth_enabled", True)
    name = f"sso-dup-{uuid4().hex[:8]}"
    response = await client.post(
        "/api/v1/mcp-servers/",
        json={
            "name": name,
            "http_url": "https://example.invalid/mcp",
            "http_auth_type": "bearer",
            "auth_scope": "per_user",
            "expected_idp_issuer": "https://idp.example/oauth2/default",
            "tools": [{"name": "dup"}, {"name": "dup"}],
        },
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 400, response.text

    listing = await client.get(
        "/api/v1/mcp-servers/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert all(item["name"] != name for item in listing.json()["items"])
